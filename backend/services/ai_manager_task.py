"""Per-Account AI Manager Task (FSM Engine) — Phase 2 Task 2.4.

Each enabled account gets one AIManagerTask instance that runs an async loop
cycling through: sleeping → monitoring → analyzing → executing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import copy
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_evaluator import AIManagerEvaluator
from backend.services.ai_manager_event_triggers import EventTriggerDetector
from backend.services.ai_manager_mtf import MultiTimeframeAnalyzer
from backend.services.ai_manager_correlation import CorrelationAnalyzer
from backend.services.ai_manager_orderbook import OrderBookMonitor

MAX_DAILY_TOKEN_BUDGET = 20_000_000

if TYPE_CHECKING:
    from backend.services.ai_account_manager_service import AIAccountManagerService

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
_EMERGENCY_CLOSE_SYMBOL_TTL_S = 30.0
_MAX_REASONING_CHARS = 2000
_CHAIN_KEY_VERSION = 1
_ALLOWED_ACTIONS = frozenset({"CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL", "FULL_CLOSE", "PARTIAL_CLOSE", "REDUCE"})


class AIManagerTask:
    """FSM-driven decision loop for a single account's AI-managed positions.

    Lifecycle states: SLEEPING → MONITORING → ANALYZING → EXECUTING, plus PAUSED and ERROR.
    Receives real-time WebSocket events (wallet/position updates), evaluates urgency via
    AIManagerEvaluator, and invokes a LangGraph-compiled decision graph when action is needed.
    Emergency fast-path bypasses the normal sleep/monitor cycle for rapid drawdown response.

    Args:
        account_id: UUID of the managed trading account.
        service: Parent AIAccountManagerService providing repo, LLM scheduler, and event bus.
        config: Validated AIManagerConfig with thresholds, limits, and feature flags.
        compiled_graph: Pre-compiled LangGraph StateGraph for decision inference.
    """

    _MAX_DRAIN_DEPTH = 3  # Max consecutive rapid evals per trigger batch

    def __init__(
        self,
        account_id: str,
        service: "AIAccountManagerService",
        config: AIManagerConfig,
        compiled_graph,
        account_label: str = "",
    ):
        self._account_id = account_id
        self._account_label = account_label or account_id[:8]
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", self._account_label)
        self._log = logging.getLogger(f"ai_manager.{safe_label}")
        self._service = service
        self._config = config
        self._graph = compiled_graph
        self._state = SLEEPING
        self._task: Optional[asyncio.Task] = None
        self._background_tasks: set[asyncio.Task] = set()
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._killed = False
        self._last_eval_symbols: Dict[str, float] = {}
        self._ws_buffer: Dict[str, Any] = {}
        self._heartbeat_at: float = 0.0
        self._evaluator = AIManagerEvaluator()
        self._emergency_in_progress: bool = False
        self._emergency_cooldown_until: float = 0.0
        self._emergency_closed_symbols: Dict[str, float] = {}  # symbol → monotonic time of last emergency close
        self._mtf_analyzer = MultiTimeframeAnalyzer()
        self._correlation_analyzer = CorrelationAnalyzer(
            correlation_threshold=self._config.correlation_threshold
        )
        self._orderbook_monitors: Dict[str, OrderBookMonitor] = {}
        self._sweep_state: Dict[str, str] = {}
        self._sweep_original_sl: Dict[str, float] = {}
        self._sweep_defense_started_at: Dict[str, float] = {}
        self._sweep_blocked_symbols: set = set()
        self._is_hedge_mode: bool = False
        self._cleanup_task: Optional[asyncio.Task] = None
        # Event-driven evaluation trigger
        self._event_trigger = EventTriggerDetector(
            price_move_pct=config.event_price_move_pct,
            drawdown_from_peak_pct=config.event_drawdown_from_peak_pct,
            pnl_velocity_pct=config.event_pnl_velocity_pct,
            volume_anomaly_multiplier=config.event_volume_anomaly_multiplier,
            staleness_alarm_s=config.staleness_alarm_s,
            funding_rate_threshold=config.event_funding_rate_threshold,
        )
        self._event_trigger_fired = asyncio.Event()
        self._last_trigger_reason: Optional[str] = None
        self._trigger_queue: list = []  # [(priority, symbol, reason)]
        self._trigger_symbol: Optional[str] = None
        self._rapid_cycle_handle = None  # asyncio.TimerHandle for queue drain debounce
        self._drain_count: int = 0  # Track consecutive rapid evals in one drain cycle
        # Dashboard enhancement attributes
        self._commentary_task: Optional[asyncio.Task] = None
        self._degradation_tier: int = 0
        self._prev_degradation_tier: int = 0
        self._next_eval_at: Optional[datetime] = None
        self._urgency_history_1h: list = []
        self._emitted_attention_ids: set = set()
        self._last_eval_completed_at: Optional[datetime] = None

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> None:
        """Spawn the async run loop as a background task."""
        self._task = asyncio.create_task(self._run(), name=f"ai-mgr-{self._account_id}")

    def _track_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _log_async(self, level: str, category: str, message: str, details: dict | None = None) -> None:
        """Fire-and-forget log write to DB."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running() and self._service and self._service._repo:
                t = loop.create_task(
                    self._service._repo.insert_log(self._account_id, level, category, message, details)
                )
                self._track_task(t)
        except RuntimeError:
            pass

    def transition_to(self, new_state: str) -> None:
        if self._state == new_state:
            return
        old_state = self._state
        self._state = new_state
        self._log.info("State transition: %s -> %s", old_state, new_state)
        self._log_async("info", "lifecycle", f"State transition: {old_state} → {new_state}")
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                t = loop.create_task(self._persist_and_emit_state())
                self._track_task(t)
                # Commentary loop management
                if new_state == MONITORING and old_state != MONITORING:
                    t2 = loop.create_task(self._start_commentary_loop())
                    self._track_task(t2)
                elif old_state == MONITORING and new_state != MONITORING:
                    t2 = loop.create_task(self._stop_commentary_loop())
                    self._track_task(t2)
        except RuntimeError:
            pass

    async def _persist_and_emit_state(self) -> None:
        try:
            if self._service and self._service._repo:
                await self._service._repo.upsert_state(self._account_id, fsm_state=self._state)
        except Exception:
            self._log.warning("Failed to persist state transition to %s in DB", self._state)
        try:
            if self._service:
                await self._service.emit_event(self._account_id, "state_change", {
                    "account_id": self._account_id, "state": self._state, "enabled": True,
                })
        except Exception:
            pass

    def cancel(self) -> None:
        """Signal cancellation and terminate the run loop task."""
        self._cancel_event.set()
        if self._rapid_cycle_handle:
            self._rapid_cycle_handle.cancel()
            self._rapid_cycle_handle = None
        if self._task and not self._task.done():
            self._task.cancel()

    def pause(self) -> None:
        """Transition to PAUSED state; the run loop blocks until resume()."""
        self.transition_to(PAUSED)
        self._pause_event.set()
        self._wake_event.set()

    def resume(self) -> None:
        """Exit PAUSED state; resumes in MONITORING or SLEEPING depending on positions."""
        if self._has_open_positions(self._ws_buffer):
            self.transition_to(MONITORING)
        else:
            self.transition_to(SLEEPING)
        self._pause_event.clear()
        self._wake_event.set()

    def set_killed(self) -> None:
        """Activate kill switch — transitions to ERROR and signals cancellation."""
        self._killed = True
        self.transition_to(ERROR)
        self._cancel_event.set()

    def reload_config(self, config: AIManagerConfig) -> None:
        """Hot-reload configuration without restarting the task."""
        self._config = config
        self._correlation_analyzer = CorrelationAnalyzer(
            correlation_threshold=config.correlation_threshold,
        )
        # Preserve baseline state (prices, regime, funding, volume) across reload
        old_prices = self._event_trigger._last_eval_prices.copy()
        old_regime = self._event_trigger._last_regime
        old_funding = self._event_trigger._last_eval_funding.copy()
        old_volume = self._event_trigger._last_eval_volume.copy()
        old_eval_time = self._event_trigger._last_eval_time
        old_trigger_time = self._event_trigger._last_trigger_time
        old_min_interval = self._event_trigger._min_trigger_interval_s
        self._event_trigger = EventTriggerDetector(
            price_move_pct=config.event_price_move_pct,
            drawdown_from_peak_pct=config.event_drawdown_from_peak_pct,
            pnl_velocity_pct=config.event_pnl_velocity_pct,
            volume_anomaly_multiplier=config.event_volume_anomaly_multiplier,
            staleness_alarm_s=config.staleness_alarm_s,
            funding_rate_threshold=config.event_funding_rate_threshold,
        )
        self._event_trigger._last_eval_prices = old_prices
        self._event_trigger._last_regime = old_regime
        self._event_trigger._last_eval_funding = old_funding
        self._event_trigger._last_eval_volume = old_volume
        self._event_trigger._last_eval_time = old_eval_time
        self._event_trigger._last_trigger_time = old_trigger_time
        self._event_trigger._min_trigger_interval_s = old_min_interval
        # Clear queue state on reload — stale queue entries from old config are unreliable
        if self._rapid_cycle_handle:
            self._rapid_cycle_handle.cancel()
            self._rapid_cycle_handle = None
        self._trigger_queue.clear()
        self._trigger_symbol = None
        self._drain_count = 0

    def is_dead(self) -> bool:
        """Return True if the run loop task has completed (normally or via exception)."""
        return self._task is not None and self._task.done()

    async def on_ws_event(self, event: dict) -> None:
        """Handle incoming WebSocket event (wallet_update or position_update).

        Updates the internal WS buffer and triggers emergency evaluation if positions
        are present and the emergency fast-path conditions are met.
        """
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
                    self._update_peak_pnl(symbol, data)
                else:
                    # Position closed — reset peak PnL tracker for this symbol
                    peaks = self._ws_buffer.get("_peak_pnl")
                    if peaks:
                        peaks.pop(symbol, None)
            except (ValueError, TypeError):
                positions.append(data)
            self._ws_buffer["positions"] = positions

        if self._state == SLEEPING and self._has_open_positions(self._ws_buffer):
            self.transition_to(MONITORING)
            self._wake_event.set()
            # Initialize trigger baselines so triggers can fire on subsequent events
            positions = self._ws_buffer.get("positions") or []
            self._event_trigger.mark_initial_prices(positions)
            # Fire trigger immediately so first position gets evaluated without waiting for safety net
            if self._config.event_driven_enabled:
                self._last_trigger_reason = "position_opened"
                self._trigger_symbol = data.get("symbol") if event_type == "position_update" else None
                self._event_trigger_fired.set()

        # Wake monitoring cycle when all positions close so it can transition to SLEEPING
        if (
            self._config.event_driven_enabled
            and self._state == MONITORING
            and not self._has_open_positions(self._ws_buffer)
        ):
            self._event_trigger_fired.set()

        # Emergency fast-path: check on every WS event (no debounce, no LLM)
        # Runs even during PAUSED — crash protection must never be gated by daily limits
        if self._state in (MONITORING, ANALYZING, PAUSED) and self._has_open_positions(self._ws_buffer):
            try:
                await self._check_emergency_close()
            except Exception:
                self._log.exception("Emergency close check failed")

        # Event-driven trigger check: evaluate if meaningful event occurred
        # Only check on position_update events (wallet updates don't affect triggers)
        if (
            event_type == "position_update"
            and self._config.event_driven_enabled
            and self._state == MONITORING
            and self._has_open_positions(self._ws_buffer)
            and not self._event_trigger_fired.is_set()
        ):
            try:
                positions = self._ws_buffer.get("positions") or []
                indicators = self._get_cached_indicators()
                peak_pnl = self._ws_buffer.get("_peak_pnl") or {}
                all_triggers = self._event_trigger.check_all_triggers(
                    positions, indicators, peak_pnl
                )
                if all_triggers:
                    # Build priority queue: [(priority, symbol, reason)]
                    self._trigger_queue = [(prio, sym, reason) for sym, reason, prio in all_triggers]
                    # Pop the highest priority as current focus
                    top = self._trigger_queue.pop(0)
                    self._trigger_symbol = top[1]
                    self._last_trigger_reason = top[2]
                    self._drain_count = 0  # Fresh batch — reset drain counter
                    self._event_trigger.mark_triggered()
                    self._event_trigger_fired.set()
                    self._log.info(
                        "Event trigger fired: %s (queue: %d more)",
                        top[2], len(self._trigger_queue),
                    )
            except Exception:
                self._log.exception("Event trigger check failed")

    def _update_peak_pnl(self, symbol: str, position_data: dict) -> None:
        """Track per-position peak unrealized PnL for drawdown-from-peak detection."""
        peaks = self._ws_buffer.setdefault("_peak_pnl", {})
        try:
            current_pnl = float(
                position_data.get("unrealisedPnl", position_data.get("unrealized_pnl", 0))
            )
        except (ValueError, TypeError):
            return
        prev_peak = peaks.get(symbol, 0.0)
        if current_pnl > prev_peak:
            peaks[symbol] = current_pnl

    async def _init_ws_buffer_from_exchange(self) -> None:
        """Fetch current positions and wallet balance from accounts_service to initialize state on startup."""
        try:
            if not self._service._accounts_service:
                return
            # Fetch positions
            positions = await self._service._accounts_service.get_positions(self._account_id) or []
            self._ws_buffer["positions"] = positions
            
            # Fetch wallet/equity
            wallet = await self._service._accounts_service.get_wallet(self._account_id) or {}
            self._ws_buffer["equity"] = wallet.get("totalEquity")
            self._ws_buffer["available_balance"] = wallet.get("totalWalletBalance")
            self._ws_buffer["wallet"] = wallet
            
            # Initialize peak PnL tracking for active positions
            for pos in positions:
                symbol = pos.get("symbol")
                if symbol:
                    self._update_peak_pnl(symbol, pos)

            self._log.info("Initialized state from exchange: %d position(s) found", len(positions))
            self._log_async("info", "lifecycle", f"Task started, {len(positions)} open position(s) found")
            
            # Transition to MONITORING if we have open positions on startup
            if self._state == SLEEPING and self._has_open_positions(self._ws_buffer):
                self.transition_to(MONITORING)
                self._wake_event.set()
                self._event_trigger.mark_initial_prices(positions)
                # Trigger immediate evaluation on cold start — don't wait 180s with unmonitored positions
                if self._config.event_driven_enabled:
                    self._last_trigger_reason = "cold_start"
                    self._event_trigger_fired.set()
        except Exception:
            self._log.exception("Failed to initialize state from exchange")
            self._log_async("error", "lifecycle", "Failed to initialize state from exchange")

    async def _run(self) -> None:
        try:
            await self._init_ws_buffer_from_exchange()
            await self._restore_sweep_state()
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

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
                    self.transition_to(SLEEPING)

        except asyncio.CancelledError:
            pass
        except Exception:
            self._log.exception("Task crashed")
            self.transition_to(ERROR)
            self._log_async("critical", "lifecycle", "Task crashed unexpectedly")
        finally:
            await self._stop_orderbook_monitors()
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _sleep_cycle(self) -> None:
        try:
            self._wake_event.clear()
            await asyncio.wait_for(self._wake_event.wait(), timeout=_HEARTBEAT_SLEEPING)
        except asyncio.TimeoutError:
            # Periodically refresh state from exchange to recover from missed WS events or startup race conditions
            await self._init_ws_buffer_from_exchange()

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
        if self._config.event_driven_enabled:
            # Event-driven: wait for trigger OR safety-net timeout
            # Do NOT clear _event_trigger_fired here — it may have been set between
            # _transition_post_eval and now. Only _transition_post_eval clears it.
            timeout = self._config.safety_net_interval_s
            if self._event_trigger_fired.is_set():
                # Trigger already pending — proceed immediately
                self._event_trigger_fired.clear()
            else:
                try:
                    await asyncio.wait_for(
                        self._wait_for_trigger_or_cancel(),
                        timeout=timeout,
                    )
                    if self._cancel_event.is_set() or self._killed:
                        return
                    self._event_trigger_fired.clear()
                except asyncio.TimeoutError:
                    self._last_trigger_reason = "safety_net_timer"
        else:
            # Legacy fixed-interval mode
            try:
                await asyncio.wait_for(
                    self._cancel_event.wait(), timeout=self._config.evaluation_interval_s
                )
                return
            except asyncio.TimeoutError:
                pass

        if self._cancel_event.is_set() or self._killed:
            return

        if not self._has_open_positions(self._ws_buffer):
            self.transition_to(SLEEPING)
            return

        # Emergency fast-path before LLM evaluation
        if await self._check_emergency_close():
            # Emergency closed positions — clear queue of potentially stale entries
            self._trigger_queue.clear()
            self._trigger_symbol = None
            self._last_trigger_reason = None
            if self._rapid_cycle_handle:
                self._rapid_cycle_handle.cancel()
                self._rapid_cycle_handle = None
            return

        # Sweep defense lifecycle: check timeouts, detect new sweeps, handle recovery
        await self._process_sweep_lifecycle()

        await self._evaluate()

    async def _wait_for_trigger_or_cancel(self) -> None:
        """Wait until either the event trigger fires or cancel is requested."""
        trigger_task = asyncio.create_task(self._event_trigger_fired.wait())
        cancel_task = asyncio.create_task(self._cancel_event.wait())
        try:
            done, pending = await asyncio.wait(
                {trigger_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            trigger_task.cancel()
            cancel_task.cancel()
            raise

    async def _evaluate(self) -> None:
        self._state = ANALYZING

        if self._service._degradation.get_tier() >= 3:
            self._transition_post_eval_aborted()
            return

        circuit_breaker = self._service._circuit_breaker
        half_open_probe = False
        if circuit_breaker.is_tripped(self._account_id):
            cooldown_ok = await circuit_breaker.check_cooldown(self._account_id)
            if not cooldown_ok:
                self._transition_post_eval_aborted()
                return
            half_open_probe = True

        try:
            async with self._service._llm_scheduler.slot(self._account_id, self._get_urgency()):
                # Token budget gate
                budget_ok = await self._service._repo.increment_token_budget_atomic(
                    self._account_id, 1000, MAX_DAILY_TOKEN_BUDGET
                )
                if not budget_ok:
                    self._log.warning("Token budget exhausted")
                    self._transition_post_eval_aborted()
                    return

                state_dict = await self._build_graph_state()

                # Dashboard enhancement: emit LLM started event
                from uuid import uuid4
                import time as _time
                _eval_cycle_id = uuid4()
                _call_id = uuid4()
                _urgency = self._get_urgency()
                await self._service.emit_event(self._account_id, "ai_manager.llm_started", {
                    "account_id": self._account_id,
                    "call_id": str(_call_id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "urgency_tier": _urgency,
                    "node_name": "action_generation",
                })
                _t0 = _time.perf_counter()

                result = await asyncio.wait_for(
                    self._graph.ainvoke(state_dict), timeout=90.0
                )

                # Dashboard enhancement: emit LLM completed event + log
                _latency_ms = int((_time.perf_counter() - _t0) * 1000)
                _success = result is not None and "action" in result
                await self._service.emit_event(self._account_id, "ai_manager.llm_call_complete", {
                    "account_id": self._account_id,
                    "id": int(_time.time() * 1000) % 2147483647,
                    "call_id": str(_call_id),
                    "evaluation_cycle_id": str(_eval_cycle_id),
                    "node_name": "action_generation",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "latency_ms": _latency_ms,
                    "input_tokens": result.get("_input_tokens", 0) if result else 0,
                    "output_tokens": result.get("_output_tokens", 0) if result else 0,
                    "model": getattr(self._service, '_model_name', 'unknown'),
                    "action_returned": result.get("action") if result else None,
                    "confidence": result.get("confidence") if result else None,
                    "reasoning_preview": result.get("reason", "")[:200] if result else None,
                    "urgency_tier": _urgency,
                    "attempt_number": 1,
                    "success": _success,
                })
                if hasattr(self._service, '_llm_logger') and self._service._llm_logger:
                    await self._service._llm_logger.log_call(
                        account_id=self._account_id,
                        call_id=_call_id,
                        evaluation_cycle_id=_eval_cycle_id,
                        node_name="action_generation",
                        timestamp=datetime.now(timezone.utc),
                        model=getattr(self._service, '_model_name', 'unknown'),
                        input_tokens=result.get("_input_tokens", 0) if result else 0,
                        output_tokens=result.get("_output_tokens", 0) if result else 0,
                        latency_ms=_latency_ms,
                        success=_success,
                        urgency_tier=_urgency,
                        action_returned=result.get("action") if result else None,
                        confidence=result.get("confidence") if result else None,
                        reasoning=result.get("reason") if result else None,
                        attempt_number=1,
                    )

                asyncio.create_task(self._persist_enrichment_data(result))
        except RuntimeError as e:
            if "slot not available" in str(e).lower():
                if half_open_probe:
                    await self._reset_half_open(circuit_breaker)
                self._transition_post_eval_aborted()
                return
            if half_open_probe:
                await self._reset_half_open(circuit_breaker)
                circuit_breaker.restart_cooldown(self._account_id)
            await self._rollback_token_budget()
            await self._service._degradation.check_health("timeout")
            self._transition_post_eval_aborted()
            return
        except Exception:
            self._log.exception("Graph evaluation failed")
            if half_open_probe:
                await self._reset_half_open(circuit_breaker)
                circuit_breaker.restart_cooldown(self._account_id)
            await self._rollback_token_budget()
            await self._service._degradation.check_health("timeout")
            self._transition_post_eval_aborted()
            return

        action = result.get("action", "HOLD")
        if action == "HOLD":
            await self._service._degradation.check_health("indeterminate")
            if half_open_probe:
                await self._reset_half_open(circuit_breaker)
            self._transition_post_eval(result.get("regime"))
            return

        await self._service._degradation.check_health("success")

        self._state = EXECUTING
        await self._execute_action(result)
        if half_open_probe and circuit_breaker.is_tripped(self._account_id):
            await self._reset_half_open(circuit_breaker)
            circuit_breaker.restart_cooldown(self._account_id)
        self._transition_post_eval(result.get("regime"))

    def _transition_post_eval(self, regime_from_result: Optional[str] = None) -> None:
        """Transition after a SUCCESSFUL evaluation (LLM actually ran)."""
        if self._state != PAUSED:
            if self._has_open_positions(self._ws_buffer):
                self.transition_to(MONITORING)
            else:
                self.transition_to(SLEEPING)
        # Reset event triggers after evaluation
        positions = self._ws_buffer.get("positions") or []
        regime = regime_from_result or self._get_cached_regime()
        indicators = self._get_cached_indicators()

        # Drain trigger queue: if more symbols need attention, schedule rapid re-eval
        # Filter stale entries (positions that closed while queued)
        open_symbols = {p.get("symbol") for p in positions if p.get("symbol")}
        self._trigger_queue = [item for item in self._trigger_queue if item[1] in open_symbols]

        # Cap rapid drain depth to prevent unbounded token consumption in volatile markets
        self._drain_count += 1
        can_drain = self._drain_count < self._MAX_DRAIN_DEPTH

        if can_drain and self._trigger_queue and self._has_open_positions(self._ws_buffer):
            # Mid-drain: only update baseline for the symbol just evaluated (not all)
            # This preserves trigger sensitivity for remaining queued and unqueued positions
            evaluated_sym = self._trigger_symbol
            if evaluated_sym:
                for pos in positions:
                    if pos.get("symbol") == evaluated_sym:
                        try:
                            mp = float(pos.get("markPrice", pos.get("mark_price", 0)))
                            if mp > 0:
                                self._event_trigger._last_eval_prices[evaluated_sym] = mp
                        except (ValueError, TypeError):
                            pass
                        break

            top = self._trigger_queue.pop(0)
            self._trigger_symbol = top[1]
            self._last_trigger_reason = top[2]
            self._event_trigger._min_trigger_interval_s = self._config.event_rapid_cycle_debounce_s
            # Schedule next eval after rapid debounce; store handle for cancellation
            try:
                loop = asyncio.get_running_loop()
                self._rapid_cycle_handle = loop.call_later(
                    self._config.event_rapid_cycle_debounce_s,
                    self._event_trigger_fired.set,
                )
            except RuntimeError:
                self._event_trigger_fired.set()
            self._log.info(
                "Queue drain: next focus %s (%s), %d remaining (drain %d/%d)",
                top[1], top[2], len(self._trigger_queue),
                self._drain_count, self._MAX_DRAIN_DEPTH,
            )
        else:
            # Queue empty or drain depth reached — full baseline reset
            self._event_trigger.mark_evaluated(positions, regime, indicators)
            if self._trigger_queue and not can_drain:
                self._log.info("Drain depth reached (%d), deferring %d queued symbols to next cycle",
                               self._MAX_DRAIN_DEPTH, len(self._trigger_queue))
            self._event_trigger._min_trigger_interval_s = 15.0
            self._event_trigger_fired.clear()
            self._last_trigger_reason = None
            self._trigger_symbol = None
            self._trigger_queue.clear()
            self._drain_count = 0

        # Dashboard: sync degradation tier and eval timing
        self._prev_degradation_tier = self._degradation_tier
        self._degradation_tier = self._service._degradation.get_tier()
        self._last_eval_completed_at = datetime.now(timezone.utc)
        interval = self._config.safety_net_interval_s if self._config.event_driven_enabled else self._config.evaluation_interval_s
        self._next_eval_at = datetime.now(timezone.utc) + timedelta(seconds=interval)

    def _transition_post_eval_aborted(self) -> None:
        """Transition after an ABORTED evaluation (LLM did NOT run — gate rejected).

        Does NOT fully reset staleness timer, but advances it enough to prevent
        hot-looping (staleness will re-fire after the debounce period, not immediately).
        """
        if self._state != PAUSED:
            if self._has_open_positions(self._ws_buffer):
                self.transition_to(MONITORING)
            else:
                self.transition_to(SLEEPING)
        self._event_trigger_fired.clear()
        self._last_trigger_reason = None
        self._trigger_symbol = None
        self._trigger_queue.clear()
        if self._rapid_cycle_handle:
            self._rapid_cycle_handle.cancel()
            self._rapid_cycle_handle = None
        # Suppress re-triggering for 60s since gates are closed.
        # Also advance _last_eval_time so staleness alarm (which bypasses debounce)
        # won't fire again until 60s from now.
        now = time.monotonic()
        self._event_trigger._last_trigger_time = now
        self._event_trigger._min_trigger_interval_s = 60.0
        self._event_trigger._last_eval_time = now - (self._event_trigger._staleness_alarm_s - 60)
        # Dashboard sync only
        self._prev_degradation_tier = self._degradation_tier
        self._degradation_tier = self._service._degradation.get_tier()

    async def _reset_half_open(self, circuit_breaker) -> None:
        try:
            if self._service._repo:
                await self._service._repo.upsert_state(
                    self._account_id, circuit_breaker_half_open_used=False
                )
        except Exception:
            self._log.warning("Failed to reset half_open_used")

    async def _execute_action(self, result: Dict[str, Any]) -> None:
        action_type = result.get("action", "HOLD")
        symbol = result.get("symbol", "")

        if self._killed:
            return

        if action_type not in _ALLOWED_ACTIONS:
            self._log.warning("Rejected invalid action_type '%s'", action_type)
            return

        # Sweep block check
        if symbol in self._sweep_blocked_symbols:
            self._log.info("Sweep block prevented execution for %s", symbol)
            return

        # Config gates
        if result.get("confidence", 0.0) < self._config.confidence_threshold:
            self._log.debug("Confidence too low for %s: %.2f < %.2f",
                         symbol, result.get("confidence", 0.0), self._config.confidence_threshold)
            return
        if symbol in self._config.excluded_symbols:
            self._log.debug("Symbol %s excluded", symbol)
            return
        if symbol in self._config.locked_positions:
            self._log.debug("Symbol %s locked", symbol)
            return

        current_positions = [p for p in (self._ws_buffer.get("positions") or []) if p.get("symbol", "") == symbol]
        if not current_positions:
            self._log.debug("Symbol %s no longer in positions", symbol)
            return
        position = current_positions[0]

        # Determine urgency for gate-skipping (FAST/EMERGENCY bypasses protective caps)
        _current_urgency = self._evaluator.classify_urgency(
            self._ws_buffer.get("positions") or [],
            self._get_market_data(),
            peak_pnl=self._ws_buffer.get("_peak_pnl"),
            emergency_pnl_velocity_pct=self._config.emergency_pnl_velocity_pct / 100,
        )
        _is_urgent = _current_urgency in ("FAST", "EMERGENCY")

        # Min position age check — skipped during urgent conditions
        if not _is_urgent and self._config.min_position_age_s and position.get("createdTime"):
            try:
                created_ms = int(position["createdTime"])
                age_s = (time.time() * 1000 - created_ms) / 1000
                if age_s < self._config.min_position_age_s:
                    self._log.debug("Position %s too young (%.0fs < %ds)",
                                 symbol, age_s, self._config.min_position_age_s)
                    return
            except (ValueError, TypeError):
                pass

        # Max single decision loss check — skipped during urgent conditions
        if not _is_urgent and self._config.max_single_decision_loss_pct:
            upnl = position.get("unrealisedPnl", position.get("unrealized_pnl", 0.0))
            equity = self._ws_buffer.get("equity")
            try:
                loss_pct = abs(float(upnl)) / float(equity) * 100 if equity and float(upnl) < 0 else 0
                if loss_pct > self._config.max_single_decision_loss_pct:
                    self._log.warning("Single decision loss %.2f%% exceeds cap %.2f%% for %s",
                                   loss_pct, self._config.max_single_decision_loss_pct, symbol)
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
            stale = [k for k, v in self._last_eval_symbols.items() if v <= cutoff]
            for k in stale:
                del self._last_eval_symbols[k]

        lock = self._service._lock_registry
        acquired = await lock.acquire(self._account_id, symbol, timeout=5.0)
        if not acquired:
            self._log.warning("Position lock unavailable for %s", symbol)
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
                self._log.error("Cannot execute action without HMAC key")
                return

            # Budget gate — must succeed before execution
            budget_ok = await self._service._repo.increment_actions_atomic(self._account_id)
            if not budget_ok:
                self._log.warning("Budget exhausted, skipping action")
                self._log_async("warning", "budget", f"Action budget exhausted, skipping {action_type} on {symbol}", {"action": action_type, "symbol": symbol})
                return

            now_utc = datetime.now(timezone.utc)
            decision_data = {
                "timestamp": now_utc,
                "action_type": action_type,
                "evaluation_type": "standard",
                "urgency": self._get_urgency(),
                "state_snapshot": copy.deepcopy(self._ws_buffer),
                "action_taken": {"action": action_type, "symbol": symbol},
                "reasoning": result.get("reason", "")[:_MAX_REASONING_CHARS],
                "confidence": result.get("confidence", 0.0),
                "graph_path": result.get("graph_path"),
                "strategy_version": self._config.strategy_version,
                "chain_key_version": _CHAIN_KEY_VERSION,
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
            self._log.exception("Execution failed for %s", symbol)
            if decision_id is not None:
                try:
                    await self._service._repo.insert_failed_outcome(
                        decision_id, decision_ts, {}, "execution_error"
                    )
                except Exception:
                    self._log.exception("Failed to record dead-letter")
            # Roll back budget since no exchange action was completed
            try:
                await self._service._repo.decrement_actions_atomic(self._account_id)
            except Exception:
                self._log.exception("Failed to roll back budget")
        finally:
            lock.release(self._account_id, symbol)

        # Post-execution bookkeeping (outside position lock)
        if exec_result is not None and decision_id is not None:
            try:
                await self._service._repo.update_decision_outcome(
                    decision_id, decision_ts, exec_result
                )
                # Only feed circuit breaker and daily limits if exchange actually closed
                if exec_result.get("status") == "closed":
                    pnl = exec_result.get("realized_pnl", 0.0)
                    await self._service._circuit_breaker.record_outcome(
                        self._account_id, pnl, action_type
                    )
                    self._log_async("info", "execution", f"Executed {action_type} on {symbol}, PnL: ${pnl:.2f}", {"action": action_type, "symbol": symbol, "pnl": pnl})
                    await self._service.emit_event(self._account_id, "execution", {
                        "action": action_type, "symbol": symbol, "pnl": pnl,
                    })
                else:
                    self._log_async("warning", "execution", f"Execution failed for {action_type} on {symbol}", {"action": action_type, "symbol": symbol})
                    await self._service.emit_event(self._account_id, "execution", {
                        "action": action_type, "symbol": symbol, "pnl": 0.0,
                        "status": "failed",
                    })
            except Exception:
                self._log.exception("Post-execution bookkeeping failed for %s", symbol)

        if exec_result is not None and exec_result.get("status") == "closed":
            try:
                await self._enforce_daily_limits(pnl)
            except Exception:
                self._log.critical("Daily limit enforcement failed — pausing as fail-safe")
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
                    self._log.warning(
                        "Daily loss cap breached: %.2f%% >= %.2f%%",
                        loss_pct, self._config.max_daily_loss_pct,
                    )
                    self.pause()
                    return

                unrealized_loss = self._get_unrealized_loss()
                total_loss_pct = ((realized_loss + unrealized_loss) / equity_start) * 100
                if total_loss_pct >= self._config.max_daily_loss_pct * 2:
                    self._log.critical(
                        "Kill switch triggered: total loss %.2f%%",
                        total_loss_pct,
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
                    self._log.info("Profit target reached")
                    self.transition_to(SLEEPING)

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
                self._log.warning("Malformed unrealisedPnl: %r", upnl)
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
            self._log.warning("Memory fetch failed")

        # Daily P&L context for the LLM
        daily_realized_pnl = 0.0
        daily_profit_target = None
        try:
            state = await self._service._repo.get_state(self._account_id)
            if state:
                daily_realized_pnl = float(state.get("realized_profit_today", 0) or 0) - float(state.get("realized_loss_today", 0) or 0)
            equity_start = await self._get_equity_at_day_start()
            if equity_start and self._config.daily_profit_target_pct:
                daily_profit_target = self._config.daily_profit_target_pct * equity_start / 100
        except Exception:
            pass

        await self._sync_orderbook_monitors()
        mtf_data = self._get_mtf_data()
        correlation_data = self._get_correlation_data()
        orderbook_data, sweep_data = self._get_orderbook_sweep_data()

        return {
            "account_id": self._account_id,
            "_logger": self._log,
            "config": self._config.model_dump(),
            "ws_snapshot": copy.deepcopy(self._ws_buffer),
            "market_data": self._get_market_data(),
            "peak_pnl": dict(self._ws_buffer.get("_peak_pnl", {})),
            "daily_realized_pnl": daily_realized_pnl,
            "daily_profit_target": daily_profit_target,
            "_evaluator": self._evaluator,
            "_llm_callable": self._service._llm_callable,
            "episodic_memory": episodic,
            "patterns": patterns,
            "decision_count": decision_count,
            "mtf": mtf_data if self._config.mtf_enabled else None,
            "correlation": correlation_data if self._config.correlation_enabled else None,
            "orderbook": orderbook_data if self._config.orderbook_enabled else None,
            "sweep": sweep_data if self._config.sweep_defense_enabled else None,
            "_sweep_blocked_symbols": list(self._sweep_blocked_symbols),
            "trigger_reason": self._last_trigger_reason or "scheduled",
            "trigger_symbol": self._trigger_symbol if self._config.event_driven_enabled else None,
            "queue_remaining": [{"symbol": sym, "reason": reason} for _, sym, reason in self._trigger_queue[:4]] if self._config.event_driven_enabled else None,
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

    def _get_cached_indicators(self) -> dict:
        """Get current indicators for event trigger checks (lightweight, no side effects)."""
        cache = self._service._market_data_cache
        if not cache:
            return {}
        return cache.get_all_indicators()

    def _get_cached_regime(self) -> Optional[str]:
        """Get the last-known market regime from the event trigger's stored state."""
        return self._event_trigger._last_regime

    def _has_open_positions(self, data: dict) -> bool:
        positions = data.get("positions") or []
        return len(positions) > 0

    # ─────────────────────────────────────────────────────────────────────────
    # Emergency close — deterministic fast-path (no LLM)
    # ─────────────────────────────────────────────────────────────────────────

    async def _check_emergency_close(self) -> bool:
        """Deterministic fast-path: close ALL losing positions on extreme signals.

        Bypasses LLM entirely. Returns True if emergency action was taken.
        """
        if not self._config.emergency_close_enabled:
            return False
        if self._killed:
            return False
        if self._emergency_in_progress:
            return False
        if self._config.dry_run:
            return False

        # Cooldown: don't re-trigger equity drop within 30s of last emergency close
        # Velocity checks still run (they're per-position, not account-wide)
        equity_cooldown_active = time.monotonic() < self._emergency_cooldown_until

        positions = self._ws_buffer.get("positions") or []
        equity = self._ws_buffer.get("equity")
        if not positions or not equity:
            return False

        try:
            equity_val = float(equity)
        except (ValueError, TypeError):
            return False

        triggered = False
        trigger_reason = ""

        # Condition 1: Account equity dropped > emergency_equity_drop_pct from reference
        # Reference ratchets upward (trailing high-water mark) to protect accumulated gains
        # Suppressed during cooldown (equity reference resets after close, needs time to stabilize)
        reference_equity = self._ws_buffer.get("_emergency_ref_equity")
        if reference_equity and reference_equity > 0:
            # Always ratchet upward even during cooldown
            if equity_val > reference_equity:
                self._ws_buffer["_emergency_ref_equity"] = equity_val
                # Persist ratchet if moved >=0.5% (throttle DB writes)
                if (equity_val - reference_equity) / reference_equity >= 0.005:
                    asyncio.ensure_future(self._persist_ref_equity(equity_val))
                reference_equity = equity_val
            if not equity_cooldown_active:
                drop_pct = ((reference_equity - equity_val) / reference_equity) * 100
                if drop_pct >= self._config.emergency_equity_drop_pct:
                    triggered = True
                    trigger_reason = f"equity_drop_{drop_pct:.1f}pct"
        elif not reference_equity:
            self._ws_buffer["_emergency_ref_equity"] = equity_val
            asyncio.ensure_future(self._persist_ref_equity(equity_val))

        # Condition 2: Per-position PnL velocity exceeds emergency threshold
        # Only close the SPECIFIC positions with extreme velocity, not all losers
        velocity_emergency_symbols: list[str] = []
        if not triggered:
            market_data = self._get_market_data()
            velocity_threshold = max(0.001, self._config.emergency_pnl_velocity_pct / 100)
            now_mono = time.monotonic()
            for pos in positions:
                symbol = pos.get("symbol", "")
                if not symbol:
                    continue
                # Per-symbol cooldown: don't re-trigger same symbol within 30s
                if now_mono - self._emergency_closed_symbols.get(symbol, 0.0) < _EMERGENCY_CLOSE_SYMBOL_TTL_S:
                    continue
                sym_indicators = market_data.get(symbol, {})
                if self._evaluator.check_emergency_signals(pos, sym_indicators, velocity_threshold):
                    velocity_emergency_symbols.append(symbol)
            if velocity_emergency_symbols:
                triggered = True
                trigger_reason = "pnl_velocity_emergency"

        if not triggered:
            return False

        # Determine which symbols to close based on trigger type
        excluded = set(self._config.excluded_symbols or [])
        locked = set(self._config.locked_positions or [])

        if trigger_reason.startswith("equity_drop"):
            # Account-wide crash: close ALL losing positions (capital preservation)
            close_symbols = []
            for pos in positions:
                symbol = pos.get("symbol", "")
                if not symbol or symbol in excluded or symbol in locked:
                    continue
                try:
                    upnl = float(pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0)))
                except (ValueError, TypeError):
                    upnl = 0.0
                if upnl < 0:
                    close_symbols.append(symbol)
        else:
            # Velocity trigger: only close the specific positions with extreme signals
            close_symbols = [s for s in velocity_emergency_symbols if s not in excluded and s not in locked]

        if not close_symbols:
            return False

        self._log.warning(
            "EMERGENCY_CLOSE triggered: reason=%s, closing %d positions",
            trigger_reason, len(close_symbols),
        )

        self._emergency_in_progress = True
        actually_closed = False
        try:
            actually_closed = await self._execute_emergency_batch_close(close_symbols, trigger_reason)
        finally:
            self._emergency_in_progress = False
            if actually_closed:
                # Record per-symbol cooldown for velocity triggers
                now_mono = time.monotonic()
                for s in close_symbols:
                    self._emergency_closed_symbols[s] = now_mono
                # Prune stale entries
                if len(self._emergency_closed_symbols) > 50:
                    cutoff = now_mono - 60.0
                    stale = [k for k, v in self._emergency_closed_symbols.items() if v <= cutoff]
                    for k in stale:
                        del self._emergency_closed_symbols[k]
                # Clear reference equity so it re-initializes from the NEXT WS wallet
                # update (which reflects post-close balance). Using current buffer value
                # would be stale (pre-close) and could re-trigger after cooldown.
                self._ws_buffer.pop("_emergency_ref_equity", None)
                # Cooldown: suppress equity-drop re-trigger for 30s
                self._emergency_cooldown_until = time.monotonic() + 30.0
        # Persist state to DB for restart recovery
        if actually_closed:
            await self._persist_emergency_state()
        return actually_closed

    async def _execute_emergency_batch_close(self, symbols: list, reason: str) -> bool:
        """Close multiple positions immediately — no LLM, no confidence, no cooldown.

        Returns True if positions were actually closed."""
        # Capture UPnL BEFORE close — WS events may remove positions from buffer during await
        symbol_set = set(symbols)
        pre_close_positions = self._ws_buffer.get("positions") or []
        estimated_upnl = 0.0
        for p in pre_close_positions:
            if p.get("symbol") in symbol_set:
                try:
                    estimated_upnl += float(p.get("unrealisedPnl", p.get("unrealized_pnl", 0)) or 0)
                except (ValueError, TypeError):
                    pass

        try:
            close_result = await asyncio.wait_for(
                self._service._close_positions_service.close_all_for_rule(
                    self._account_id,
                    rule_id=None,
                    symbols=symbols,
                ),
                timeout=30.0,
            )
            if close_result.get("skipped"):
                self._log.warning(
                    "Emergency batch close SKIPPED (concurrent close in progress), reason=%s",
                    reason,
                )
                return False
            closed = close_result.get("closed", 0)
            self._log.info(
                "Emergency batch close completed: closed=%d, reason=%s",
                closed, reason,
            )
            self._log_async("critical", "emergency", f"Emergency close: {closed} position(s) closed. Reason: {reason}", {"symbols": symbols, "closed": closed, "reason": reason})

            # Track realized loss for daily limit enforcement
            realized_pnl = close_result.get("realized_pnl")
            if realized_pnl is None:
                realized_pnl = estimated_upnl
            try:
                pnl_val = float(realized_pnl) if realized_pnl else 0.0
                if pnl_val < 0:
                    await self._enforce_daily_limits(pnl_val)
            except Exception:
                self._log.warning("Daily limit tracking failed after emergency close")

            # Emit execution event for frontend/WS listeners
            try:
                await self._service.emit_event(self._account_id, "execution", {
                    "action": "EMERGENCY_CLOSE", "symbols": symbols,
                    "pnl": float(realized_pnl or 0), "reason": reason,
                })
            except Exception:
                pass

            # Record as decision for audit trail
            if hasattr(self._service, '_repo') and self._service._repo:
                decision_data = {
                    "timestamp": datetime.now(timezone.utc),
                    "action_type": "EMERGENCY_CLOSE",
                    "evaluation_type": "emergency",
                    "urgency": "EMERGENCY",
                    "state_snapshot": {"symbols": symbols, "reason": reason},
                    "action_taken": {"action": "EMERGENCY_CLOSE", "symbol": ",".join(symbols), "symbols": symbols},
                    "reasoning": f"Deterministic emergency close: {reason}",
                    "confidence": 1.0,
                    "graph_path": "emergency_fast_path",
                    "strategy_version": self._config.strategy_version,
                    "chain_key_version": _CHAIN_KEY_VERSION,
                }
                await self._service._repo.insert_decision(
                    self._account_id, decision_data,
                    self._service._hmac_key or "no-hmac-configured",
                )
            return True
        except Exception:
            self._log.exception("Emergency batch close FAILED")
            return False

    async def _update_heartbeat(self) -> None:
        try:
            await self._service._repo.update_heartbeat(self._account_id)
        except Exception:
            self._log.warning("Heartbeat update failed")

    # ─────────────────────────────────────────────────────────────────────────
    # Emergency state persistence (survives restart)
    # ─────────────────────────────────────────────────────────────────────────

    def _restore_emergency_state(self, state: dict) -> None:
        """Restore emergency close state from DB after restart."""
        ref_equity = state.get("emergency_ref_equity")
        if ref_equity is not None:
            self._ws_buffer["_emergency_ref_equity"] = float(ref_equity)

        cooldown_until = state.get("emergency_cooldown_until")
        if cooldown_until is not None:
            if isinstance(cooldown_until, str):
                cooldown_until = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
            if cooldown_until.tzinfo is None:
                cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
            remaining = (cooldown_until - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                self._emergency_cooldown_until = time.monotonic() + remaining

        closed_symbols = state.get("emergency_closed_symbols")
        if closed_symbols:
            if isinstance(closed_symbols, str):
                closed_symbols = json.loads(closed_symbols)
            now_mono = time.monotonic()
            now_utc = datetime.now(timezone.utc)
            for sym, ts_str in closed_symbols.items():
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_s = (now_utc - ts).total_seconds()
                if age_s < _EMERGENCY_CLOSE_SYMBOL_TTL_S:
                    self._emergency_closed_symbols[sym] = now_mono - age_s

    async def _persist_emergency_state(self) -> None:
        """Write emergency close state to DB for restart recovery."""
        now_utc = datetime.now(timezone.utc)
        now_mono = time.monotonic()

        ref_eq = self._ws_buffer.get("_emergency_ref_equity")

        cooldown_until = None
        remaining = self._emergency_cooldown_until - now_mono
        if remaining > 0:
            cooldown_until = now_utc + timedelta(seconds=remaining)

        symbols_json: dict = {}
        for sym, mono_ts in self._emergency_closed_symbols.items():
            age = now_mono - mono_ts
            if age < _EMERGENCY_CLOSE_SYMBOL_TTL_S:
                symbols_json[sym] = (now_utc - timedelta(seconds=age)).isoformat()

        try:
            await self._service._repo.upsert_state(
                self._account_id,
                emergency_ref_equity=ref_eq,
                emergency_cooldown_until=cooldown_until,
                emergency_closed_symbols=json.dumps(symbols_json),
            )
        except Exception:
            self._log.warning("Failed to persist emergency state")

    async def _persist_ref_equity(self, value: float) -> None:
        """Persist reference equity ratchet to DB (fire-and-forget)."""
        try:
            await self._service._repo.upsert_state(
                self._account_id, emergency_ref_equity=value,
            )
        except Exception:
            self._log.warning("Failed to persist ref equity", exc_info=True)

    async def _rollback_token_budget(self) -> None:
        """Roll back the 1000-token budget increment on LLM call failure."""
        try:
            await self._service._repo.decrement_token_budget_atomic(self._account_id, 1000)
        except Exception:
            self._log.warning("Failed to roll back token budget", exc_info=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Sweep defense helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _process_sweep_lifecycle(self) -> None:
        """Run sweep defense checks each monitoring cycle."""
        if not self._config.sweep_defense_enabled:
            return
        try:
            # 1. Check timeouts on active defenses
            for symbol in list(self._sweep_state.keys()):
                if self._sweep_state.get(symbol) == "DEFENDING":
                    await self._check_sweep_timeout(symbol)

            # 2. Check for new sweeps and resolved defenses
            positions = self._ws_buffer.get("positions") or []
            for pos in positions:
                symbol = pos.get("symbol", "")
                if not symbol:
                    continue
                monitor = self._orderbook_monitors.get(symbol)
                if not monitor:
                    continue

                # Use original SL for active defenses (position SL may have been cancelled/widened)
                current_state = self._sweep_state.get(symbol, "INACTIVE")
                if current_state == "DEFENDING":
                    my_sl = self._sweep_original_sl.get(symbol) or None
                else:
                    my_sl = float(pos.get("stopLoss", 0) or 0) or None
                my_side = pos.get("side", "Buy")
                current_price = float(pos.get("markPrice", 0) or 0)
                _, sweep = monitor.get_snapshot(my_sl, my_side, current_price)

                if current_state == "INACTIVE" and sweep:
                    await self._handle_sweep_detected(symbol, sweep, my_sl or 0.0)
                elif current_state == "DEFENDING" and not sweep:
                    await self._handle_sweep_resolved(symbol)
        except Exception:
            self._log.warning("Sweep lifecycle error", exc_info=True)

    async def _modify_stop_loss(self, symbol: str, new_sl: Optional[float], side: str = "") -> bool:
        try:
            client = await self._service._accounts_service.get_client(self._account_id)
            sl_str = str(new_sl) if new_sl else "0"
            pos_idx = 0
            if side and self._is_hedge_mode:
                pos_idx = 1 if side == "Buy" else 2
            await client.set_trading_stop(symbol=symbol, stop_loss=sl_str, position_idx=pos_idx)
            return True
        except Exception:
            self._log.exception("Failed to modify SL for %s", symbol)
            return False

    async def _restore_sweep_state(self) -> None:
        """Restore sweep defense state from DB on startup."""
        try:
            saved = await self._service._repo.get_sweep_state(self._account_id)
        except Exception:
            self._log.warning("Failed to load sweep state")
            return

        now = time.time()
        timeout_s = self._config.sweep_recovery_timeout_candles * 300

        for symbol, data in saved.items():
            state = data.get("state", "INACTIVE")
            if state in ("DEFENDING", "DETECTED"):
                started = data.get("started_at_epoch", now)
                if now - started > timeout_s:
                    original_sl = data.get("original_sl")
                    if original_sl:
                        await self._modify_stop_loss(symbol, original_sl)
                    self._log.warning("Sweep defense expired during restart for %s, restored SL", symbol)
                else:
                    self._sweep_state[symbol] = state
                    self._sweep_original_sl[symbol] = data.get("original_sl", 0.0)
                    self._sweep_defense_started_at[symbol] = started
                    self._sweep_blocked_symbols.add(symbol)
                    self._log.info("Resumed sweep defense for %s", symbol)

    # ─────────────────────────────────────────────────────────────────────────
    # Enrichment data helpers for _build_graph_state
    # ─────────────────────────────────────────────────────────────────────────

    def _get_mtf_data(self) -> Optional[Dict[str, Any]]:
        try:
            cache = self._service._market_data_cache
            if not cache:
                return None
            positions = self._ws_buffer.get("positions") or []
            symbols = {p.get("symbol") for p in positions if p.get("symbol")}
            # Return MTF for the first symbol that has data (primary position)
            # In multi-position scenarios, the LLM sees per-position context via market_data
            for sym in symbols:
                klines = cache.get_mtf_klines(sym)
                if klines and len(klines) >= 2:
                    return self._mtf_analyzer.compute_signal(sym, klines)
        except Exception:
            self._log.debug("MTF data fetch failed, skipping")
        return None

    def _get_correlation_data(self) -> Optional[Dict[str, Any]]:
        try:
            positions = self._ws_buffer.get("positions") or []
            if len(positions) < 2:
                return None
            cache = self._service._market_data_cache
            if not cache:
                return None
            symbols = {p.get("symbol") for p in positions if p.get("symbol")}
            klines = {sym: {"1h": cache.get_klines(sym, "1h") or []} for sym in symbols}
            return self._correlation_analyzer.compute(positions, klines)
        except Exception:
            self._log.debug("Correlation data fetch failed, defaulting to zero heat")
            return {"portfolio_heat": 0.0, "matrix": {}, "clusters": [], "max_correlated_exposure_pct": 0.0}

    def _get_orderbook_sweep_data(self):
        positions = self._ws_buffer.get("positions") or []
        if not positions:
            return None, None
        best_ob = None
        best_sweep = None
        best_confidence = 0.0
        for pos in positions:
            symbol = pos.get("symbol", "")
            monitor = self._orderbook_monitors.get(symbol)
            if not monitor:
                continue
            # Use original SL during active defense (position SL may be cancelled/widened)
            if self._sweep_state.get(symbol) == "DEFENDING":
                my_sl = self._sweep_original_sl.get(symbol) or None
            else:
                my_sl = float(pos.get("stopLoss", 0) or 0) or None
            my_side = pos.get("side", "Buy")
            current_price = float(pos.get("markPrice", 0) or 0)
            ob_snapshot, sweep = monitor.get_snapshot(my_sl, my_side, current_price)
            if best_ob is None:
                best_ob = ob_snapshot
            if sweep and sweep.get("confidence", 0) > best_confidence:
                best_confidence = sweep["confidence"]
                best_sweep = sweep
                best_ob = ob_snapshot
        return best_ob, best_sweep

    # ─────────────────────────────────────────────────────────────────────────
    # OrderBook monitor lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def _start_orderbook_monitor(self, symbol: str) -> None:
        if not self._config.orderbook_enabled:
            return
        if symbol not in self._orderbook_monitors:
            monitor = OrderBookMonitor(symbol, self._config.sweep_confidence_threshold)
            self._orderbook_monitors[symbol] = monitor
            await monitor.start()

    async def _stop_orderbook_monitors(self) -> None:
        for monitor in self._orderbook_monitors.values():
            await monitor.stop()
        self._orderbook_monitors.clear()

    async def _sync_orderbook_monitors(self) -> None:
        if not self._config.orderbook_enabled:
            return
        positions = self._ws_buffer.get("positions") or []
        active_symbols = {p.get("symbol") for p in positions if p.get("symbol")}
        for sym in active_symbols:
            if sym not in self._orderbook_monitors:
                await self._start_orderbook_monitor(sym)
        stale = set(self._orderbook_monitors.keys()) - active_symbols
        for sym in stale:
            monitor = self._orderbook_monitors.pop(sym)
            await monitor.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # Enrichment persistence and periodic cleanup
    # ─────────────────────────────────────────────────────────────────────────

    async def _persist_enrichment_data(self, state: Dict[str, Any]) -> None:
        repo = self._service._repo
        account_id = self._account_id
        symbol = state.get("symbol", "")
        try:
            regime_detail = state.get("regime_detail")
            if regime_detail:
                await repo.insert_regime_history(
                    account_id, symbol=symbol,
                    regime=state.get("regime", "ranging"),
                    confidence=regime_detail.get("confidence", 0.0),
                    detail=regime_detail,
                )
            correlation = state.get("correlation")
            if correlation and correlation.get("portfolio_heat", 0) > 0:
                positions = self._ws_buffer.get("positions") or []
                await repo.insert_correlation_snapshot(
                    account_id,
                    portfolio_heat=correlation["portfolio_heat"],
                    matrix=correlation.get("matrix", {}),
                    clusters=correlation.get("clusters", []),
                    position_count=len(positions),
                )
            orderbook = state.get("orderbook")
            if orderbook:
                await repo.insert_orderbook_snapshot(
                    account_id, symbol=symbol,
                    imbalance_ratio=orderbook.get("imbalance_ratio", 1.0),
                    spread_bps=orderbook.get("spread_bps", 0.0),
                    depth_ratio=orderbook.get("depth_ratio", 1.0),
                    bid_clusters=orderbook.get("bid_clusters", []),
                    ask_clusters=orderbook.get("ask_clusters", []),
                    spoofing_flags=orderbook.get("spoofing_flags", []),
                )
        except Exception:
            self._log.debug("Failed to persist enrichment data for %s", account_id)

    async def _persist_sweep_state(self) -> None:
        state_dict = {}
        for symbol, state in self._sweep_state.items():
            if state in ("DEFENDING", "DETECTED"):
                state_dict[symbol] = {
                    "state": state,
                    "original_sl": self._sweep_original_sl.get(symbol, 0),
                    "started_at_epoch": self._sweep_defense_started_at.get(symbol, 0),
                }
        try:
            await self._service._repo.update_sweep_state(self._account_id, state_dict)
        except Exception:
            self._log.warning("Failed to persist sweep state")

    async def _handle_sweep_detected(self, symbol: str, sweep: Dict[str, Any], current_sl: float) -> None:
        """Handle sweep detection → DETECTED → DEFENDING."""
        confidence = sweep.get("confidence", 0)

        self._sweep_state[symbol] = "DETECTED"
        await self._service._repo.insert_sweep_event(
            self._account_id,
            symbol=symbol, event_type="detected",
            confidence=confidence, direction=sweep.get("direction", "unknown"),
            swept_level=sweep.get("swept_level"), original_sl=current_sl,
        )

        self._sweep_state[symbol] = "DEFENDING"
        self._sweep_original_sl[symbol] = current_sl
        self._sweep_defense_started_at[symbol] = time.time()
        self._sweep_blocked_symbols.add(symbol)

        if confidence >= 0.75:
            await self._modify_stop_loss(symbol, None)
            defense_action = "cancel_sl"
        elif confidence >= 0.5:
            wider_sl = current_sl * 0.995 if sweep.get("direction") == "long_hunt" else current_sl * 1.005
            await self._modify_stop_loss(symbol, wider_sl)
            defense_action = "widen_sl"
        else:
            defense_action = "monitor_only"

        await self._persist_sweep_state()
        await self._service._repo.insert_sweep_event(
            self._account_id,
            symbol=symbol, event_type="defense_activated",
            confidence=confidence, direction=sweep.get("direction", "unknown"),
            swept_level=sweep.get("swept_level"), original_sl=current_sl,
            defense_action=defense_action, detail=sweep,
        )

    async def _handle_sweep_resolved(self, symbol: str) -> None:
        """Handle sweep recovery → restore SL."""
        original_sl = self._sweep_original_sl.get(symbol)
        if original_sl:
            positions = self._ws_buffer.get("positions") or []
            if any(p.get("symbol") == symbol for p in positions):
                await self._modify_stop_loss(symbol, original_sl)

        self._sweep_state.pop(symbol, None)
        self._sweep_original_sl.pop(symbol, None)
        self._sweep_defense_started_at.pop(symbol, None)
        self._sweep_blocked_symbols.discard(symbol)

        await self._persist_sweep_state()
        await self._service._repo.insert_sweep_event(
            self._account_id,
            symbol=symbol, event_type="resolved", confidence=0.0, direction="",
            original_sl=original_sl, outcome="recovered",
        )

    async def _check_sweep_timeout(self, symbol: str) -> None:
        """Check if sweep defense has timed out."""
        started = self._sweep_defense_started_at.get(symbol, 0)
        timeout_candles = self._config.sweep_recovery_timeout_candles
        if timeout_candles <= 0:
            return
        timeout_s = timeout_candles * 300
        if time.time() - started > timeout_s:
            original_sl = self._sweep_original_sl.get(symbol)
            if original_sl:
                positions = self._ws_buffer.get("positions") or []
                if any(p.get("symbol") == symbol for p in positions):
                    await self._modify_stop_loss(symbol, original_sl)

            self._sweep_state.pop(symbol, None)
            self._sweep_original_sl.pop(symbol, None)
            self._sweep_defense_started_at.pop(symbol, None)
            self._sweep_blocked_symbols.discard(symbol)

            await self._persist_sweep_state()
            await self._service._repo.insert_sweep_event(
                self._account_id,
                symbol=symbol, event_type="timeout", confidence=0.0, direction="",
                original_sl=original_sl, outcome="timed_out",
                duration_ms=int((time.time() - started) * 1000),
            )

    async def _periodic_cleanup(self) -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await self._service._repo.cleanup_old_data()
            except Exception:
                logger.debug("Data cleanup failed, will retry next hour")

    # --- Dashboard Enhancement: Helper Methods ---

    def _get_live_positions(self) -> list:
        """Return current positions from WS buffer."""
        return self._ws_buffer.get("positions") or []

    def _get_analysis_context(self) -> dict:
        """Return current enrichment context for dashboard display."""
        mtf_data = self._get_mtf_data() if hasattr(self, '_get_mtf_data') else None
        correlation_data = self._get_correlation_data() if hasattr(self, '_get_correlation_data') else None
        orderbook_data, sweep_data = (None, None)
        if hasattr(self, '_get_orderbook_sweep_data'):
            orderbook_data, sweep_data = self._get_orderbook_sweep_data()

        # Map MTF trend to regime label
        regime_label = None
        if mtf_data and isinstance(mtf_data, dict):
            trend = mtf_data.get("trend")
            if trend == "bullish":
                regime_label = "trending_up"
            elif trend == "bearish":
                regime_label = "trending_down"
            elif trend:
                regime_label = trend  # "mixed" etc.

        positions = self._get_live_positions()
        return {
            "regime": {"label": regime_label} if regime_label else None,
            "session": None,  # Session detection not yet implemented
            "correlation_heat": correlation_data.get("portfolio_heat") if correlation_data and isinstance(correlation_data, dict) else None,
            "active_sweeps": [
                {"symbol": sym, "confidence": 0.5, "direction": "unknown"}
                for sym in (self._sweep_state.keys() if self._sweep_state else [])
            ],
            "positions_health": [
                {"symbol": p.get("symbol", ""), "health_score": max(0, 100 - abs(int(p.get("drawdown_from_peak", 0) or 0))), "concern": None}
                for p in positions
            ],
            "day_score_justification": None,
            "evaluation_cycle_id": None,
        }

    def _get_dashboard_state(self) -> dict:
        """Return task state dict for capabilities aggregator."""
        state: Dict[str, Any] = {}
        if self._sweep_state:
            state["active_sweep_symbols"] = list(self._sweep_state.keys())
        return state

    def _compute_pnl_trend(self) -> str:
        """Compute unrealized PnL trend (rising/falling/flat)."""
        positions = self._get_live_positions()
        if not positions:
            return "flat"
        total_upnl = sum(float(p.get("unrealisedPnl", 0) or p.get("current_upnl", 0) or 0) for p in positions)
        if total_upnl > 0:
            return "rising"
        elif total_upnl < 0:
            return "falling"
        return "flat"

    def _get_token_budget_pct(self) -> float:
        """Return current token budget usage percentage."""
        status = self._ws_buffer.get("_token_budget")
        if status and isinstance(status, dict):
            used = status.get("used", 0)
            max_val = status.get("max", MAX_DAILY_TOKEN_BUDGET)
            if max_val > 0:
                return (used / max_val) * 100
        return 0.0

    # --- Dashboard Enhancement: Commentary Loop (Task 1.9) ---

    async def _start_commentary_loop(self) -> None:
        if getattr(self, '_commentary_task', None) is not None:
            return
        self._commentary_task = asyncio.create_task(self._commentary_loop())

    async def _stop_commentary_loop(self) -> None:
        task = getattr(self, '_commentary_task', None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._commentary_task = None

    async def _commentary_loop(self) -> None:
        COMMENTARY_INTERVAL_S = 300
        while True:
            await asyncio.sleep(COMMENTARY_INTERVAL_S)
            try:
                await self._generate_commentary_once()
            except Exception as e:
                logger.warning("Commentary generation failed for %s: %s", self._account_id, e)

    async def _generate_commentary_once(self) -> None:
        from backend.services.ai_manager_commentary import compute_day_score, generate_template_commentary

        context = self._get_analysis_context()
        positions = self._get_live_positions()

        score, label, justification = compute_day_score(
            regime_label=context.get("regime", {}).get("label") if isinstance(context.get("regime"), dict) else context.get("regime"),
            position_directions=[p.get("side", "") for p in positions],
            unrealized_pnl_trend=self._compute_pnl_trend(),
            urgency_history_1h=getattr(self, '_urgency_history_1h', []),
            correlation_heat=context.get("correlation_heat"),
        )

        regime_label = context.get("regime", {}).get("label") if isinstance(context.get("regime"), dict) else context.get("regime")
        summary = generate_template_commentary(
            regime_label=regime_label,
            session=context.get("session"),
            positions=positions,
            day_score=score,
            day_score_label=label,
        )

        commentary_id = await self._service._repo.insert_commentary(
            self._account_id, "template", regime_label or "unknown",
            score, label, summary,
            [p.get("symbol", "") for p in positions],
        )

        await self._service.emit_event(self._account_id, "ai_manager.market_commentary", {
            "account_id": self._account_id,
            "commentary_id": commentary_id,
            "day_score": score,
            "day_score_label": label,
            "summary_text": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "regime": regime_label,
            "symbols_referenced": [p.get("symbol", "") for p in positions],
        })

    # --- Dashboard Enhancement: Attention Triggers (Task 1.10) ---

    async def _check_attention_triggers(self, eval_result: dict, prev_urgency: str, curr_urgency: str) -> None:
        if not hasattr(self, '_emitted_attention_ids'):
            self._emitted_attention_ids: set = set()

        items_to_emit: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        if prev_urgency == "STANDARD" and curr_urgency == "FAST":
            items_to_emit.append({
                "id": f"urg-{self._account_id}-{int(time.time())}",
                "severity": "warning",
                "title": "Urgency Escalated to FAST",
                "description": "Evaluation urgency increased — market conditions require faster response.",
                "timestamp": now,
                "source": "urgency_escalation",
            })
        elif curr_urgency == "EMERGENCY":
            items_to_emit.append({
                "id": f"emrg-{self._account_id}-{int(time.time())}",
                "severity": "critical",
                "title": "EMERGENCY Detected",
                "description": "Emergency conditions triggered. Immediate protective action taken.",
                "timestamp": now,
                "source": "urgency_escalation",
            })

        for sweep in getattr(self, '_active_sweep_signals', []):
            if sweep.get("confidence", 0) >= 0.5:
                item_id = f"sweep-{sweep.get('symbol')}-{int(time.time())}"
                if item_id not in self._emitted_attention_ids:
                    items_to_emit.append({
                        "id": item_id,
                        "severity": "warning",
                        "title": f"Sweep Detected: {sweep.get('symbol')}",
                        "description": f"Stop-hunt sweep detected with {sweep['confidence']:.0%} confidence.",
                        "timestamp": now,
                        "source": "sweep_detection",
                    })
                    self._emitted_attention_ids.add(item_id)

        budget_pct = self._get_token_budget_pct() if hasattr(self, '_get_token_budget_pct') else 0
        if budget_pct > 80 and "budget_80" not in self._emitted_attention_ids:
            items_to_emit.append({
                "id": "budget_80",
                "severity": "info",
                "title": "Token Budget at 80%",
                "description": "AI commentary frequency may reduce as budget approaches limit.",
                "timestamp": now,
                "source": "budget_warning",
            })
            self._emitted_attention_ids.add("budget_80")

        if hasattr(self, '_prev_degradation_tier') and self._degradation_tier > self._prev_degradation_tier:
            items_to_emit.append({
                "id": f"degrad-{self._degradation_tier}-{int(time.time())}",
                "severity": "warning",
                "title": f"Degradation Tier Increased to {self._degradation_tier}",
                "description": "Some AI capabilities are operating in reduced mode.",
                "timestamp": now,
                "source": "degradation",
            })

        for pos in self._get_live_positions():
            if pos.get("drawdown_from_peak", 0) > 40:
                item_id = f"dd-{pos.get('symbol', 'unknown')}-{int(time.time())}"
                if item_id not in self._emitted_attention_ids:
                    items_to_emit.append({
                        "id": item_id,
                        "severity": "critical",
                        "title": f"High Drawdown: {pos.get('symbol', 'unknown')}",
                        "description": "Position drawdown exceeds 40% from peak profit.",
                        "timestamp": now,
                        "source": "drawdown",
                    })
                    self._emitted_attention_ids.add(item_id)

        for item in items_to_emit:
            item["dismissed"] = False
            await self._service.emit_event(self._account_id, "ai_manager.attention_needed", {
                "account_id": self._account_id,
                "item": item,
            })

    # --- Dashboard Enhancement: Cleanup Scheduling (Task 1.12) ---

    async def _daily_dashboard_cleanup(self) -> None:
        try:
            deleted_calls = await self._service._repo.cleanup_old_llm_calls(days=90)
            deleted_commentary = await self._service._repo.cleanup_old_commentary(days=7)
            if deleted_calls or deleted_commentary:
                logger.info("Daily cleanup for %s: removed %d LLM calls, %d commentary entries",
                            self._account_id, deleted_calls, deleted_commentary)
        except Exception as e:
            logger.warning("Daily dashboard cleanup failed for %s: %s", self._account_id, e)
