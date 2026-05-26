"""Per-Account AI Manager Task (FSM Engine) — Phase 2 Task 2.4.

Each enabled account gets one AIManagerTask instance that runs an async loop
cycling through: sleeping → monitoring → analyzing → executing.
"""

from __future__ import annotations

import asyncio
import logging
import time
import copy
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_evaluator import AIManagerEvaluator

MAX_DAILY_TOKEN_BUDGET = 100_000

if TYPE_CHECKING:
    from backend.services.ai_account_manager_service import AIAccountManagerService

logger = logging.getLogger(__name__)

# FSM states
SLEEPING = "sleeping"
MONITORING = "monitoring"
ANALYZING = "analyzing"
EXECUTING = "executing"
PAUSED = "paused"
ERROR = "error"

_HEARTBEAT_SLEEPING = 60.0
_HEARTBEAT_MONITORING = 10.0
_SYMBOL_COOLDOWN_S = 15.0
_ALLOWED_ACTIONS = frozenset({"CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL", "FULL_CLOSE", "PARTIAL_CLOSE", "REDUCE"})


class AIManagerTask:
    """Manages one account's AI decision loop."""

    def __init__(
        self,
        account_id: str,
        service: "AIAccountManagerService",
        config: AIManagerConfig,
        compiled_graph,
    ):
        self._account_id = account_id
        self._service = service
        self._config = config
        self._graph = compiled_graph
        self._state = SLEEPING
        self._task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._killed = False
        self._last_eval_symbols: Dict[str, float] = {}
        self._ws_buffer: Dict[str, Any] = {}
        self._heartbeat_at: float = 0.0
        self._evaluator = AIManagerEvaluator()

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"ai-mgr-{self._account_id}")

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._task and not self._task.done():
            self._task.cancel()

    def pause(self) -> None:
        self._state = PAUSED
        self._pause_event.set()

    def resume(self) -> None:
        if self._has_open_positions(self._ws_buffer):
            self._state = MONITORING
        else:
            self._state = SLEEPING
        self._pause_event.clear()
        self._wake_event.set()

    def set_killed(self) -> None:
        self._killed = True
        self._cancel_event.set()

    def reload_config(self, config: AIManagerConfig) -> None:
        self._config = config

    def is_dead(self) -> bool:
        return self._task is not None and self._task.done()

    async def on_ws_event(self, event: dict) -> None:
        event_type = event.get("type")
        data = event.get("data", {})

        if event_type == "wallet_update":
            self._ws_buffer["equity"] = data.get("totalEquity")
            self._ws_buffer["available_balance"] = data.get("totalWalletBalance")
            self._ws_buffer["wallet"] = data
        elif event_type == "position_update":
            positions = self._ws_buffer.get("positions") or []
            symbol = data.get("symbol")
            size = data.get("size", "0")
            positions = [p for p in positions if p.get("symbol") != symbol]
            try:
                if size and float(size) != 0:
                    positions.append(data)
            except (ValueError, TypeError):
                positions.append(data)
            self._ws_buffer["positions"] = positions

        if self._state == SLEEPING and self._has_open_positions(self._ws_buffer):
            self._state = MONITORING
            self._wake_event.set()

    async def _run(self) -> None:
        try:
            while not self._cancel_event.is_set():
                if self._killed:
                    break

                self._heartbeat_at = time.monotonic()
                await self._update_heartbeat()

                if self._state == PAUSED:
                    await self._wait_for_resume()
                    continue

                if self._state == SLEEPING:
                    await self._sleep_cycle()
                elif self._state == MONITORING:
                    await self._monitoring_cycle()
                elif self._state in (ANALYZING, EXECUTING):
                    await self._evaluate()
                elif self._state == ERROR:
                    await asyncio.sleep(30.0)
                    self._state = SLEEPING

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("AIManagerTask %s crashed", self._account_id)
            self._state = ERROR

    async def _sleep_cycle(self) -> None:
        try:
            self._wake_event.clear()
            await asyncio.wait_for(self._wake_event.wait(), timeout=_HEARTBEAT_SLEEPING)
        except asyncio.TimeoutError:
            pass

    async def _wait_for_resume(self) -> None:
        self._wake_event.clear()
        while not self._wake_event.is_set():
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=300.0)
            except asyncio.TimeoutError:
                await self._update_heartbeat()
                if self._cancel_event.is_set():
                    return

    async def _monitoring_cycle(self) -> None:
        try:
            await asyncio.wait_for(
                self._cancel_event.wait(), timeout=self._config.evaluation_interval_s
            )
            return  # cancel_event was set
        except asyncio.TimeoutError:
            pass

        if self._cancel_event.is_set() or self._killed:
            return

        if not self._has_open_positions(self._ws_buffer):
            self._state = SLEEPING
            return

        await self._evaluate()

    async def _evaluate(self) -> None:
        self._state = ANALYZING

        if self._service._degradation.get_tier() >= 3:
            self._transition_post_eval()
            return

        circuit_breaker = self._service._circuit_breaker
        half_open_probe = False
        if circuit_breaker.is_tripped(self._account_id):
            cooldown_ok = await circuit_breaker.check_cooldown(self._account_id)
            if not cooldown_ok:
                self._transition_post_eval()
                return
            half_open_probe = True

        try:
            async with self._service._llm_scheduler.slot(self._account_id, self._get_urgency()):
                # Token budget gate
                budget_ok = await self._service._repo.increment_token_budget_atomic(
                    self._account_id, 1000, MAX_DAILY_TOKEN_BUDGET
                )
                if not budget_ok:
                    logger.warning("Token budget exhausted for %s", self._account_id)
                    self._transition_post_eval()
                    return

                state_dict = await self._build_graph_state()
                result = await asyncio.wait_for(
                    self._graph.ainvoke(state_dict), timeout=90.0
                )
        except RuntimeError as e:
            if "slot not available" in str(e).lower():
                if half_open_probe:
                    await self._reset_half_open(circuit_breaker)
                self._transition_post_eval()
                return
            if half_open_probe:
                await self._reset_half_open(circuit_breaker)
                circuit_breaker.restart_cooldown(self._account_id)
            await self._service._degradation.check_health("timeout")
            self._transition_post_eval()
            return
        except Exception:
            logger.exception("Graph evaluation failed for %s", self._account_id)
            if half_open_probe:
                await self._reset_half_open(circuit_breaker)
                circuit_breaker.restart_cooldown(self._account_id)
            await self._service._degradation.check_health("timeout")
            self._transition_post_eval()
            return

        action = result.get("action", "HOLD")
        if action == "HOLD":
            await self._service._degradation.check_health("indeterminate")
            if half_open_probe:
                await self._reset_half_open(circuit_breaker)
            self._transition_post_eval()
            return

        await self._service._degradation.check_health("success")

        self._state = EXECUTING
        await self._execute_action(result)
        if half_open_probe and circuit_breaker.is_tripped(self._account_id):
            await self._reset_half_open(circuit_breaker)
            circuit_breaker.restart_cooldown(self._account_id)
        self._transition_post_eval()

    def _transition_post_eval(self) -> None:
        if self._state != PAUSED:
            if self._has_open_positions(self._ws_buffer):
                self._state = MONITORING
            else:
                self._state = SLEEPING
        asyncio.ensure_future(self._emit_state_change())

    async def _emit_state_change(self) -> None:
        try:
            await self._service.emit_event(self._account_id, "state_change", {
                "account_id": self._account_id, "state": self._state, "enabled": True,
            })
        except Exception:
            pass

    async def _reset_half_open(self, circuit_breaker) -> None:
        try:
            if self._service._repo:
                await self._service._repo.upsert_state(
                    self._account_id, circuit_breaker_half_open_used=False
                )
        except Exception:
            logger.warning("Failed to reset half_open_used for %s", self._account_id)

    async def _execute_action(self, result: Dict[str, Any]) -> None:
        action_type = result.get("action", "HOLD")
        symbol = result.get("symbol", "")

        if self._killed:
            return

        if action_type not in _ALLOWED_ACTIONS:
            logger.warning("Rejected invalid action_type '%s' for %s", action_type, self._account_id)
            return

        if self._config.dry_run:
            logger.info("dry_run: would execute %s %s for %s", action_type, symbol, self._account_id)
            return

        # Config gates
        if result.get("confidence", 0.0) < self._config.confidence_threshold:
            logger.debug("Confidence too low for %s %s: %.2f < %.2f",
                         self._account_id, symbol, result.get("confidence", 0.0), self._config.confidence_threshold)
            return
        if symbol in self._config.excluded_symbols:
            logger.debug("Symbol %s excluded for %s", symbol, self._account_id)
            return
        if symbol in self._config.locked_positions:
            logger.debug("Symbol %s locked for %s", symbol, self._account_id)
            return

        current_positions = [p for p in (self._ws_buffer.get("positions") or []) if p.get("symbol", "") == symbol]
        if not current_positions:
            logger.debug("Symbol %s no longer in positions for %s", symbol, self._account_id)
            return
        position = current_positions[0]

        # Min position age check
        if self._config.min_position_age_s and position.get("createdTime"):
            try:
                created_ms = int(position["createdTime"])
                age_s = (time.time() * 1000 - created_ms) / 1000
                if age_s < self._config.min_position_age_s:
                    logger.debug("Position %s too young (%.0fs < %ds) for %s",
                                 symbol, age_s, self._config.min_position_age_s, self._account_id)
                    return
            except (ValueError, TypeError):
                pass

        # Max single decision loss check
        if self._config.max_single_decision_loss_pct:
            upnl = position.get("unrealisedPnl", position.get("unrealized_pnl", 0.0))
            equity = self._ws_buffer.get("equity")
            try:
                loss_pct = abs(float(upnl)) / float(equity) * 100 if equity and float(upnl) < 0 else 0
                if loss_pct > self._config.max_single_decision_loss_pct:
                    logger.warning("Single decision loss %.2f%% exceeds cap %.2f%% for %s %s",
                                   loss_pct, self._config.max_single_decision_loss_pct, self._account_id, symbol)
                    return
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        # Per-symbol cooldown (checked before lock, recorded after lock)
        now_mono = time.monotonic()
        last_eval = self._last_eval_symbols.get(symbol, 0.0)
        if now_mono - last_eval < _SYMBOL_COOLDOWN_S:
            return

        if len(self._last_eval_symbols) > 100:
            cutoff = now_mono - 60.0
            self._last_eval_symbols = {k: v for k, v in self._last_eval_symbols.items() if v > cutoff}

        lock = self._service._lock_registry
        acquired = await lock.acquire(self._account_id, symbol, timeout=5.0)
        if not acquired:
            logger.warning("Position lock unavailable: %s %s", self._account_id, symbol)
            return

        # Record cooldown only after lock acquired
        self._last_eval_symbols[symbol] = now_mono

        decision_id = None
        decision_ts = None
        pnl = 0.0
        exec_result = None
        try:
            # Re-check kill switch AFTER acquiring lock (TOCTOU defense)
            kill_active = await self._service._repo.is_kill_switch_active(self._account_id)
            if kill_active:
                return

            if not self._service._hmac_key:
                logger.error("Cannot execute action without HMAC key for %s", self._account_id)
                return

            # Budget gate — must succeed before execution
            budget_ok = await self._service._repo.increment_actions_atomic(self._account_id)
            if not budget_ok:
                logger.warning("Budget exhausted for %s, skipping action", self._account_id)
                return

            now_utc = datetime.now(timezone.utc)
            decision_data = {
                "timestamp": now_utc,
                "action_type": action_type,
                "evaluation_type": "standard",
                "urgency": self._get_urgency(),
                "state_snapshot": copy.deepcopy(self._ws_buffer),
                "action_taken": {"action": action_type, "symbol": symbol},
                "reasoning": result.get("reason", "")[:2000],
                "confidence": result.get("confidence", 0.0),
                "graph_path": result.get("graph_path"),
                "strategy_version": self._config.strategy_version,
                "chain_key_version": 1,
            }

            decision_id, decision_ts = await self._service._repo.insert_decision(
                self._account_id, decision_data, self._service._hmac_key
            )

            close_result = await asyncio.wait_for(
                self._service._close_positions_service.close_all_for_rule(
                    self._account_id,
                    rule_id=None,
                    symbols=[symbol],
                ),
                timeout=30.0,
            )
            # Use position's unrealized PnL as estimated realized (close converts unrealized → realized)
            estimated_pnl = 0.0
            try:
                upnl = position.get("unrealisedPnl", position.get("unrealized_pnl", 0.0))
                estimated_pnl = float(upnl)
            except (TypeError, ValueError):
                pass
            exec_result = {
                "status": "closed" if close_result.get("closed", 0) > 0 else "failed",
                "realized_pnl": estimated_pnl,
                "close_result": close_result,
            }

        except Exception:
            logger.exception("Execution failed for %s %s", self._account_id, symbol)
            if decision_id is not None:
                try:
                    await self._service._repo.insert_failed_outcome(
                        decision_id, decision_ts, {}, "execution_error"
                    )
                except Exception:
                    logger.exception("Failed to record dead-letter for %s", self._account_id)
            else:
                logger.error("Budget consumed but no decision created for %s %s", self._account_id, symbol)
        finally:
            lock.release(self._account_id, symbol)

        # Post-execution bookkeeping (outside position lock)
        if exec_result is not None and decision_id is not None:
            try:
                await self._service._repo.update_decision_outcome(
                    decision_id, decision_ts, exec_result or {}
                )
                # Only feed circuit breaker and daily limits if exchange actually closed
                if exec_result.get("status") == "closed":
                    pnl = exec_result.get("realized_pnl", 0.0) if exec_result else 0.0
                    await self._service._circuit_breaker.record_outcome(
                        self._account_id, pnl, action_type
                    )
                    await self._service.emit_event(self._account_id, "execution", {
                        "action": action_type, "symbol": symbol, "pnl": pnl,
                    })
                else:
                    await self._service.emit_event(self._account_id, "execution", {
                        "action": action_type, "symbol": symbol, "pnl": 0.0,
                        "status": "failed",
                    })
            except Exception:
                logger.exception("Post-execution bookkeeping failed for %s %s", self._account_id, symbol)

        try:
            await self._enforce_daily_limits(pnl)
        except Exception:
            logger.critical("Daily limit enforcement failed for %s — pausing as fail-safe", self._account_id)
            self.pause()

    async def _enforce_daily_limits(self, pnl: float) -> None:
        """Task 3.5: Daily loss enforcement after every AI-initiated close."""
        equity_start = await self._get_equity_at_day_start()

        if pnl < 0:
            loss_data = await self._service._repo.record_realized_loss(self._account_id, abs(pnl))
            realized_loss = loss_data.get("realized_loss_today", 0.0)

            if equity_start and equity_start > 0:
                loss_pct = (realized_loss / equity_start) * 100
                if loss_pct >= self._config.max_daily_loss_pct:
                    logger.warning(
                        "Daily loss cap breached for %s: %.2f%% >= %.2f%%",
                        self._account_id, loss_pct, self._config.max_daily_loss_pct,
                    )
                    self.pause()
                    return

                unrealized_loss = self._get_unrealized_loss()
                total_loss_pct = ((realized_loss + unrealized_loss) / equity_start) * 100
                if total_loss_pct >= self._config.max_daily_loss_pct * 2:
                    logger.critical(
                        "Kill switch triggered for %s: total loss %.2f%%",
                        self._account_id, total_loss_pct,
                    )
                    await self._service._repo.set_kill_switch(self._account_id, True)
                    self.set_killed()
                    return

        if pnl > 0:
            profit_data = await self._service._repo.record_realized_profit(self._account_id, pnl)
            if self._config.daily_profit_target_pct and equity_start and equity_start > 0:
                realized_profit = profit_data.get("realized_profit_today", 0.0)
                target = self._config.daily_profit_target_pct * equity_start / 100
                if realized_profit >= target:
                    logger.info("Profit target reached for %s", self._account_id)
                    self._state = SLEEPING

    async def _init_equity_at_day_start(self) -> Optional[float]:
        """Atomically initialize equity_at_day_start if NULL."""
        equity = self._ws_buffer.get("equity")
        if equity is None:
            return None
        await self._service._repo.init_equity_at_day_start(self._account_id, float(equity))
        return float(equity)

    async def _get_equity_at_day_start(self) -> Optional[float]:
        state = await self._service._repo.get_state(self._account_id)
        if not state:
            return None
        equity = state.get("equity_at_day_start")
        if equity is None:
            return await self._init_equity_at_day_start()
        return float(equity)

    def _get_unrealized_loss(self) -> float:
        """Sum negative unrealized PnL from current positions."""
        positions = self._ws_buffer.get("positions") or []
        total = 0.0
        for pos in positions:
            upnl = pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0.0))
            try:
                val = float(upnl)
                if val < 0:
                    total += abs(val)
            except (TypeError, ValueError):
                logger.warning("Malformed unrealisedPnl for %s: %r", self._account_id, upnl)
        return total

    async def _build_graph_state(self) -> Dict[str, Any]:
        episodic = []
        patterns = []
        decision_count = 100
        try:
            if hasattr(self._service, '_memory') and self._service._memory:
                episodic, patterns, decision_count = await asyncio.gather(
                    self._service._memory.get_episodic_context(self._account_id),
                    self._service._memory.get_semantic_patterns(self._account_id),
                    self._service._memory.get_decision_count(self._account_id),
                )
        except Exception:
            logger.warning("Memory fetch failed for %s", self._account_id)

        return {
            "account_id": self._account_id,
            "config": self._config.model_dump(),
            "ws_snapshot": copy.deepcopy(self._ws_buffer),
            "market_data": self._get_market_data(),
            "_evaluator": self._evaluator,
            "_llm_callable": self._service._llm_callable,
            "episodic_memory": episodic,
            "patterns": patterns,
            "decision_count": decision_count,
        }

    def _get_urgency(self) -> str:
        tier = self._service._degradation.get_tier()
        if tier == 0:
            return "FAST"
        return "STANDARD"

    def _get_market_data(self) -> dict:
        cache = self._service._market_data_cache
        if not cache:
            return {}
        positions = self._ws_buffer.get("positions") or []
        symbols = {p.get("symbol") for p in positions if p.get("symbol")}
        if symbols:
            cache.track_symbols(symbols)
        return cache.get_all_indicators()

    def _has_open_positions(self, data: dict) -> bool:
        positions = data.get("positions") or []
        return len(positions) > 0

    async def _update_heartbeat(self) -> None:
        try:
            await self._service._repo.update_heartbeat(self._account_id)
        except Exception:
            logger.warning("Heartbeat update failed for %s", self._account_id)
