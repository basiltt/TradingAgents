"""Trading Cycle Engine — orchestrates batch trading from scan results."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import asyncpg

from backend.services.cycle_repository import CycleRepository

logger = logging.getLogger(__name__)

CONFIDENCE_ORDER = {"none": 0, "low": 1, "moderate": 2, "high": 3}

ALLOWED_STOP_REASONS = frozenset({
    "target_reached", "drawdown_breached", "all_trades_failed",
    "circuit_breaker", "insufficient_balance", "user_stopped",
    "server_shutdown", "server_restart", "max_duration_exceeded",
    "rule_triggered",
})


class CycleError(Exception):
    code: str = "UNKNOWN_ERROR"
    safe_message: str = "Operation failed."


class CycleAlreadyActiveError(CycleError):
    code = "CYCLE_ALREADY_ACTIVE"
    safe_message = "An active cycle already exists for this account."


class InsufficientEquityError(CycleError):
    code = "INSUFFICIENT_EQUITY"
    safe_message = "Insufficient equity for this configuration."


class NoQualifyingResultsError(CycleError):
    code = "NO_QUALIFYING_RESULTS"
    safe_message = "No symbols match your filters."


class ScanNotFoundError(CycleError):
    code = "SCAN_NOT_FOUND"
    safe_message = "Scan not found."


class ScanTooOldError(CycleError):
    code = "SCAN_TOO_OLD"
    safe_message = "Scan results are too old."


class CloseRuleLimitError(CycleError):
    code = "CLOSE_RULE_LIMIT"
    safe_message = "Close rule limit reached for this account."


class InsufficientPermissionsError(CycleError):
    code = "INSUFFICIENT_PERMISSIONS"
    safe_message = "Bybit API key lacks required permissions."


class AccountNotConfiguredError(CycleError):
    code = "ACCOUNT_NOT_CONFIGURED"
    safe_message = "Account infrastructure not configured."


class CycleNotFoundError(CycleError):
    code = "CYCLE_NOT_FOUND"
    safe_message = "Cycle not found."


class CycleNotRunningError(CycleError):
    code = "CYCLE_NOT_RUNNING"
    safe_message = "Cycle is not in a stoppable state."


class TradingCycleEngine:
    def __init__(
        self,
        cycle_repo: CycleRepository,
        accounts_svc: Any,
        close_positions_svc: Any,
        db: Any,
        ws_manager: Any = None,
        *,
        bybit_concurrency: int = 3,
        circuit_breaker_threshold: int = 3,
        max_duration_seconds: int = 300,
        max_scan_age_seconds: int = 7200,
    ):
        self._repo = cycle_repo
        self._accounts = accounts_svc
        self._close_positions = close_positions_svc
        self._db = db
        self._ws_manager = ws_manager
        self._concurrency = bybit_concurrency
        self._cb_threshold = circuit_breaker_threshold
        self._max_duration = max_duration_seconds
        self._max_scan_age = max_scan_age_seconds
        self._active_tasks: dict[int, asyncio.Task] = {}
        self._lifecycle_callbacks: list[callable] = []
        self._sweep_task: Optional[asyncio.Task] = None

    def register_lifecycle_callback(self, callback: callable) -> None:
        self._lifecycle_callbacks.append(callback)

    async def _notify(self, event_type: str, payload: dict) -> None:
        for cb in self._lifecycle_callbacks:
            try:
                await cb(event_type, payload)
            except Exception:
                logger.exception("Lifecycle callback error")

    async def start(self) -> None:
        await self._startup_recovery()
        self._sweep_task = asyncio.create_task(self._sweep_loop())

    async def shutdown(self) -> None:
        if self._sweep_task:
            self._sweep_task.cancel()
        tasks = dict(self._active_tasks)
        for task in tasks.values():
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        self._active_tasks.clear()
        for cycle_id in tasks:
            await self._finalize_cycle(cycle_id, "failed", "server_shutdown")

    async def list_cycles(
        self, offset: int = 0, limit: int = 20, *, status: Optional[str] = None
    ) -> tuple[list[dict], int]:
        return await self._repo.list_cycles(offset, limit, status=status)

    async def get_cycle(self, cycle_id: int) -> Optional[dict]:
        return await self._repo.get_cycle(cycle_id)

    @staticmethod
    def filter_scan_results(scan_results: list[dict], config: dict) -> list[dict]:
        min_score = config.get("min_score", 3)
        min_conf = config.get("min_confidence", "moderate")
        sig_filter = config.get("signal_filter", "both")
        max_trades = config.get("max_trades", 20)
        min_conf_val = CONFIDENCE_ORDER.get(min_conf, 2)

        filtered = []
        for r in scan_results:
            if r.get("score", 0) < min_score:
                continue
            if CONFIDENCE_ORDER.get(r.get("confidence", "none"), 0) < min_conf_val:
                continue
            direction = r.get("direction", "hold")
            if direction == "hold":
                continue
            if sig_filter != "both" and direction != sig_filter:
                continue
            filtered.append(r)

        filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
        return filtered[:max_trades]

    async def start_cycle(self, config: Any) -> dict:
        cfg = config if isinstance(config, dict) else config.__dict__
        account_id = cfg["account_id"]
        scan_id = cfg["scan_id"]

        account = await self._db.get_account(account_id)
        if not account or not account.get("is_active"):
            raise AccountNotConfiguredError()

        scan = await self._db.get_scan(scan_id)
        if not scan:
            raise ScanNotFoundError()

        started = scan.get("started_at")
        if started:
            try:
                scan_time = datetime.fromisoformat(started) if isinstance(started, str) else started
                if scan_time.tzinfo is None:
                    scan_time = scan_time.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - scan_time).total_seconds()
                if age > self._max_scan_age:
                    raise ScanTooOldError()
            except (ValueError, TypeError):
                pass

        filtered = self.filter_scan_results(scan.get("results", []), cfg)
        if not filtered:
            raise NoQualifyingResultsError()

        rule_counts = await self._db.count_active_rules_by_account()
        current_count = rule_counts.get(account_id, 0)
        if current_count >= 9:
            raise CloseRuleLimitError()

        try:
            cycle_id = await self._repo.create_cycle(cfg)
        except asyncpg.UniqueViolationError:
            raise CycleAlreadyActiveError()

        task = asyncio.create_task(self._execute_cycle(cycle_id, filtered, cfg))
        self._active_tasks[cycle_id] = task

        cycle = await self._repo.get_cycle(cycle_id)
        return cycle

    async def stop_cycle(self, cycle_id: int) -> dict:
        ok = await self._repo.update_status(
            cycle_id, "stopping",
        )
        if not ok:
            cycle = await self._repo.get_cycle(cycle_id)
            if not cycle:
                raise CycleNotFoundError()
            if cycle["status"] in ("stopping", "stopped", "completed", "failed"):
                return cycle
            raise CycleNotRunningError()

        task = self._active_tasks.get(cycle_id)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        await self._finalize_cycle(cycle_id, "stopped", "user_stopped")
        cycle = await self._repo.get_cycle(cycle_id)
        return cycle

    async def dry_run(self, config: Any) -> dict:
        cfg = config if isinstance(config, dict) else config.__dict__
        account_id = cfg["account_id"]
        scan_id = cfg["scan_id"]

        account = await self._db.get_account(account_id)
        if not account or not account.get("is_active"):
            raise AccountNotConfiguredError()

        scan = await self._db.get_scan(scan_id)
        if not scan:
            raise ScanNotFoundError()

        age = 0.0
        started = scan.get("started_at")
        if started:
            try:
                scan_time = datetime.fromisoformat(started) if isinstance(started, str) else started
                if scan_time.tzinfo is None:
                    scan_time = scan_time.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - scan_time).total_seconds()
                if age > self._max_scan_age:
                    raise ScanTooOldError()
            except (ValueError, TypeError):
                pass

        filtered = self.filter_scan_results(scan.get("results", []), cfg)
        if not filtered:
            raise NoQualifyingResultsError()

        wallet = await self._accounts.get_wallet(account_id)
        equity = float(wallet.get("totalEquity", 0))
        if equity <= 0:
            raise InsufficientEquityError()

        positions = await self._accounts.get_positions(account_id)
        position_symbols = {
            p["symbol"] for p in positions if float(p.get("size", 0)) > 0
        }
        conflicting = [r["ticker"] for r in filtered if r["ticker"] in position_symbols]
        effective = [r for r in filtered if r["ticker"] not in position_symbols]

        capital_pct = float(cfg.get("capital_pct", 5))
        capital_per_trade = equity * (capital_pct / 100)
        total_capital_pct = capital_pct * len(effective)

        target_type = cfg.get("target_type", "percentage")
        target_value = float(cfg.get("target_value", 10))
        max_drawdown_pct = float(cfg.get("max_drawdown_pct", 5))

        if target_type == "percentage":
            balance_above = equity * (1 + target_value / 100)
        else:
            balance_above = equity + target_value
        balance_below = equity * (1 - max_drawdown_pct / 100)

        warnings: list[str] = []
        if conflicting:
            warnings.append(f"Existing positions on {', '.join(conflicting)} — these symbols will be skipped.")
        if age > self._max_scan_age / 2:
            warnings.append("Scan results are over 1 hour old — consider rescanning.")
        if target_type == "percentage" and abs(target_value - max_drawdown_pct) < 2:
            warnings.append("Target and drawdown thresholds are very close — risk of premature stop.")
        if total_capital_pct > 80:
            warnings.append(f"Total capital allocation is {total_capital_pct:.0f}% — high exposure.")

        return {
            "qualifying_symbols": [r["ticker"] for r in effective],
            "estimated_trades": len(effective),
            "balance_above_threshold": balance_above,
            "balance_below_threshold": balance_below,
            "estimated_capital_per_trade": capital_per_trade,
            "total_capital_pct": total_capital_pct,
            "current_equity": equity,
            "warnings": warnings,
        }

    async def _execute_cycle(
        self, cycle_id: int, filtered: list[dict], cfg: dict
    ) -> None:
        try:
            await self._run_cycle(cycle_id, filtered, cfg)
        except asyncio.CancelledError:
            self._active_tasks.pop(cycle_id, None)
            raise
        except Exception as e:
            logger.warning("Cycle %d failed unexpectedly: %s", cycle_id, e)
            await self._finalize_cycle(cycle_id, "failed", "circuit_breaker")
        finally:
            self._active_tasks.pop(cycle_id, None)

    async def _run_cycle(
        self, cycle_id: int, filtered: list[dict], cfg: dict
    ) -> None:
        account_id = cfg["account_id"]
        await self._repo.update_status(cycle_id, "placing_trades")
        await self._notify("cycle.status_change", {
            "cycle_id": cycle_id, "status": "placing_trades", "account_id": account_id,
        })

        wallet = await self._accounts.get_wallet(account_id)
        initial_equity = float(wallet.get("totalEquity", 0))
        if initial_equity <= 0:
            await self._finalize_cycle(cycle_id, "failed", "insufficient_balance")
            return

        positions = await self._accounts.get_positions(account_id)
        position_symbols = {
            p["symbol"] for p in positions if float(p.get("size", 0)) > 0
        }

        semaphore = asyncio.Semaphore(self._concurrency)
        cb_failures = 0
        trades_placed = 0
        trades_failed = 0
        trades_total = len(filtered)

        for item in filtered:
            symbol = item["ticker"]
            direction = item["direction"]

            if symbol in position_symbols:
                logger.warning("Skipping %s — existing position", symbol)
                await self._repo.add_trade(cycle_id, {
                    "symbol": symbol, "side": "Buy",
                    "status": "cancelled", "error_msg": "existing_position",
                })
                trades_failed += 1
                await self._repo.increment_counters(cycle_id, failed=1)
                continue

            trade_direction = cfg.get("trade_direction", "straight")
            if trade_direction == "straight":
                side = "Buy" if direction == "buy" else "Sell"
            else:
                side = "Sell" if direction == "buy" else "Buy"

            order_link_id = f"cycle-{cycle_id}-{uuid.uuid4().hex[:12]}"
            trade_id = await self._repo.add_trade(cycle_id, {
                "symbol": symbol, "side": side,
                "order_link_id": order_link_id, "status": "submitted",
            })

            try:
                async with semaphore:
                    tp_pct = cfg.get("take_profit_pct")
                    sl_pct = cfg.get("stop_loss_pct")
                    result = await self._accounts.place_trade(
                        account_id=account_id,
                        symbol=symbol,
                        signal_direction=direction,
                        trade_direction=trade_direction,
                        leverage=int(cfg.get("leverage", 10)),
                        take_profit_pct=float(tp_pct) if tp_pct else 0,
                        stop_loss_pct=float(sl_pct) if sl_pct else 0,
                        capital_pct=float(cfg.get("capital_pct", 5)),
                        base_capital=initial_equity,
                    )
                order_id = result.get("orderId") or result.get("order_id")
                await self._repo.update_trade(
                    trade_id, status="filled", order_id=order_id,
                    filled_at=datetime.now(timezone.utc),
                )
                trades_placed += 1
                await self._repo.increment_counters(cycle_id, placed=1)
                cb_failures = 0
            except Exception as e:
                err_msg = str(e)[:500]
                retcode = getattr(e, "ret_code", None)
                if retcode == 110043:
                    await self._repo.update_trade(trade_id, status="failed", error_msg="insufficient_balance")
                    trades_failed += 1
                    await self._repo.increment_counters(cycle_id, failed=1)
                    logger.warning("Cycle %d: insufficient balance at %s, aborting", cycle_id, symbol)
                    break
                await self._repo.update_trade(trade_id, status="failed", error_msg=err_msg)
                trades_failed += 1
                await self._repo.increment_counters(cycle_id, failed=1)
                cb_failures += 1
                if cb_failures >= self._cb_threshold:
                    logger.warning("Cycle %d: circuit breaker triggered after %d failures", cycle_id, cb_failures)
                    break

            await self._notify("cycle.progress", {
                "cycle_id": cycle_id, "status": "placing_trades",
                "trades_placed": trades_placed, "trades_total": trades_total,
                "account_id": account_id,
            })
            await asyncio.sleep(0.1)

        if trades_placed == 0:
            await self._finalize_cycle(cycle_id, "failed", "all_trades_failed")
            return

        target_type = cfg.get("target_type", "percentage")
        target_value = float(cfg.get("target_value", 10))
        max_drawdown_pct = float(cfg.get("max_drawdown_pct", 5))
        intended_trades = len(filtered)
        if trades_placed < intended_trades:
            fill_ratio = trades_placed / intended_trades
            target_value *= fill_ratio
            max_drawdown_pct *= fill_ratio
            logger.info(
                "Cycle %d: partial fill %d/%d, scaling target/drawdown by %.2f",
                cycle_id, trades_placed, intended_trades, fill_ratio,
            )

        balance_below = Decimal(str(initial_equity)) * (1 - Decimal(str(max_drawdown_pct)) / 100)
        await self._db.insert_close_rule({
            "account_id": account_id,
            "trigger_type": "BALANCE_BELOW",
            "threshold_value": balance_below,
            "reference_value": Decimal(str(initial_equity)),
            "status": "pending_activation",
            "cycle_id": cycle_id,
        })

        if target_type == "percentage":
            balance_above = Decimal(str(initial_equity)) * (1 + Decimal(str(target_value)) / 100)
        else:
            balance_above = Decimal(str(initial_equity)) + Decimal(str(target_value))

        await self._db.insert_close_rule({
            "account_id": account_id,
            "trigger_type": "BALANCE_ABOVE",
            "threshold_value": balance_above,
            "reference_value": Decimal(str(initial_equity)),
            "status": "pending_activation",
            "cycle_id": cycle_id,
        })

        await self._activate_cycle_rules(cycle_id)
        await self._repo.update_status(
            cycle_id, "running",
            initial_equity=initial_equity,
            started_at=datetime.now(timezone.utc),
        )
        await self._notify("cycle.status_change", {
            "cycle_id": cycle_id, "status": "running", "account_id": account_id,
        })

    async def _finalize_cycle(
        self, cycle_id: int, terminal_status: str, stop_reason: str
    ) -> None:
        if stop_reason not in ALLOWED_STOP_REASONS:
            stop_reason = "circuit_breaker"

        cycle = await self._repo.get_cycle(cycle_id)
        if not cycle or cycle["status"] in ("completed", "stopped", "failed"):
            return

        account_id = cycle["account_id"]

        ok = await self._repo.update_status(
            cycle_id, terminal_status,
            stop_reason=stop_reason,
            completed_at=datetime.now(timezone.utc),
        )
        if not ok:
            return

        await self._expire_cycle_rules(cycle_id)

        if stop_reason in ("user_stopped", "server_shutdown", "server_restart", "max_duration_exceeded"):
            try:
                symbols = await self._repo.get_cycle_trade_symbols(cycle_id)
                if symbols:
                    result = await self._close_positions.close_all_for_rule(
                        account_id, None, symbols=symbols,
                    )
                    if result.get("skipped"):
                        logger.warning("Position close skipped for cycle %d (concurrent close in progress)", cycle_id)
            except Exception:
                logger.warning("Failed to close positions for cycle %d on stop", cycle_id)

        await self._notify("cycle.status_change", {
            "cycle_id": cycle_id, "status": terminal_status,
            "account_id": account_id,
        })

    async def _activate_cycle_rules(self, cycle_id: int) -> None:
        await self._repo.activate_cycle_rules(cycle_id)

    async def _expire_cycle_rules(self, cycle_id: int) -> None:
        await self._repo.expire_cycle_rules(cycle_id)

    async def on_rule_triggered(self, rule: dict) -> None:
        cycle_id = rule.get("cycle_id")
        if not cycle_id:
            return
        trigger_type = rule.get("trigger_type", "")
        if trigger_type == "BALANCE_ABOVE":
            reason = "target_reached"
        elif trigger_type == "BALANCE_BELOW":
            reason = "drawdown_breached"
        else:
            reason = "rule_triggered"

        ok = await self._repo.update_status(cycle_id, "stopping")
        if not ok:
            return

        task = self._active_tasks.get(cycle_id)
        if task and not task.done():
            task.cancel()

        await self._finalize_cycle(cycle_id, "completed" if reason == "target_reached" else "stopped", reason)

    async def _startup_recovery(self) -> None:
        stuck = await self._repo.find_all_non_terminal_cycles()
        for cycle in stuck:
            cycle_id = cycle["id"]
            logger.warning("Recovering stuck cycle %d (status=%s)", cycle_id, cycle["status"])
            await self._repo.reconcile_counters(cycle_id)
            await self._expire_cycle_rules(cycle_id)
            await self._repo.update_status(
                cycle_id, "failed", stop_reason="server_restart",
                completed_at=datetime.now(timezone.utc),
            )
        if stuck:
            logger.info("Recovered %d stuck cycles on startup", len(stuck))

    async def _sweep_loop(self) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return
        while True:
            try:
                stuck = await self._repo.find_stuck_cycles(self._max_duration)
                for cycle in stuck:
                    if cycle["id"] not in self._active_tasks:
                        logger.warning("Sweep: cycle %d stuck, finalizing", cycle["id"])
                        await self._finalize_cycle(
                            cycle["id"], "failed", "max_duration_exceeded"
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Sweep loop error")
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
