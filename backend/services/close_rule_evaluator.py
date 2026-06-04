"""Background service that evaluates conditional close rules via real-time WS events (debounced 1.5s) with a 60s polling fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

EVALUATION_INTERVAL = 60  # seconds
PER_ACCOUNT_TIMEOUT = 30  # seconds — must accommodate closing multiple positions
MAX_CONCURRENT_ACCOUNTS = 5
MAX_RULE_FAILURES = 3
_STARTUP_DELAY_S = 15
_STUCK_RULE_RECOVERY_AGE_S = 90


class CloseRuleEvaluator:
    """Evaluates active close rules against live prices and triggers closures.

    Combines real-time WebSocket event evaluation (debounced 1.5s) with a 60s
    polling fallback. Supports TP, SL, trailing stop, and time-based rules.
    Processes accounts concurrently (up to MAX_CONCURRENT_ACCOUNTS).
    """

    def __init__(self, close_service: Any, accounts_service: Any, db: Any):
        self._close_service = close_service
        self._cycle_callback: Optional[Any] = None
        self._cycle_repo: Optional[Any] = None
        self._accounts_service = accounts_service
        self._db = db
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._shutting_down = False
        self._rule_failures: dict[str, int] = {}
        self._last_ws_eval: dict[str, float] = {}
        self._ws_debounce_interval = 1.5
        self._ws_eval_locks: dict[str, asyncio.Lock] = {}
        self._rules_cache: dict[str, list] = {}
        self._get_active_trailing: Callable[[], set] = lambda: set()
        self._trailing_peaks: dict[str, dict[str, float]] = {}  # {account_id: {symbol: peak_pnl}}

    def set_trailing_checker(self, fn: Callable[[], set]) -> None:
        """Set a callback that returns currently trailing symbols."""
        self._get_active_trailing = fn

    def set_cycle_callback(self, callback: Any) -> None:
        """Set the callback invoked when a cycle-bound rule triggers."""
        self._cycle_callback = callback

    def set_cycle_repo(self, repo: Any) -> None:
        """Inject the cycle repository for cycle-rule linkage."""
        self._cycle_repo = repo

    async def start(self) -> None:
        """Start the background evaluation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())
        logger.info("CloseRuleEvaluator started (interval=%ds)", EVALUATION_INTERVAL)

    async def shutdown(self) -> None:
        """Stop the evaluation loop and cancel the background task."""
        self._running = False
        self._shutting_down = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CloseRuleEvaluator stopped")

    async def _evaluation_loop(self) -> None:
        try:
            await asyncio.sleep(_STARTUP_DELAY_S)
        except asyncio.CancelledError:
            return

        while self._running:
            try:
                await self._evaluate_all_rules()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Rule evaluation cycle failed")
            try:
                await asyncio.sleep(EVALUATION_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _evaluate_all_rules(self) -> None:
        try:
            recovered = await self._db.recover_stuck_triggered_rules(_STUCK_RULE_RECOVERY_AGE_S)
            if recovered:
                logger.warning("Recovered %d stuck triggered rules", recovered)
        except Exception:
            logger.exception("Failed to recover stuck triggered rules")

        rules = await self._db.list_active_rules()
        if not rules:
            return

        accounts: dict[str, list[dict]] = {}
        for rule in rules:
            aid = rule["account_id"]
            accounts.setdefault(aid, []).append(rule)

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNTS)

        async def evaluate_account(account_id: str, account_rules: list[dict]) -> None:
            async with semaphore:
                try:
                    await asyncio.wait_for(
                        self._evaluate_account_rules(account_id, account_rules),
                        timeout=PER_ACCOUNT_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Rule evaluation timed out for account %s", account_id)
                except Exception:
                    logger.exception("Rule evaluation failed for account %s", account_id)

        await asyncio.gather(*[
            evaluate_account(aid, arules) for aid, arules in accounts.items()
        ])

        active_ids = {r["id"] for r in rules}
        self._rule_failures = {k: v for k, v in self._rule_failures.items() if k in active_ids}
        active_account_ids = set(accounts.keys())
        self._last_ws_eval = {k: v for k, v in self._last_ws_eval.items() if k in active_account_ids}
        self._ws_eval_locks = {k: v for k, v in self._ws_eval_locks.items() if k in active_account_ids}
        self._rules_cache = {k: v for k, v in self._rules_cache.items() if k in active_account_ids}
        self._trailing_peaks = {k: v for k, v in self._trailing_peaks.items() if k in active_account_ids}

    async def on_wallet_update(self, account_id: str, wallet_data: dict) -> None:
        """Evaluate equity-based rules instantly on WS wallet event.

        Drawdown rules (EQUITY_DROP_PCT) bypass debounce for fastest reaction.
        Profit/other rules keep 1.5s debounce to reduce noise.
        """
        if self._shutting_down:
            return

        # WS events arrive as {"type": "...", "data": {...}} — only process wallet updates
        event_type = wallet_data.get("type")
        if event_type and event_type != "wallet_update":
            return
        data = wallet_data.get("data", wallet_data) if event_type else wallet_data

        try:
            equity = Decimal(data.get("totalEquity") or "0")
            pnl = Decimal(data.get("totalPerpUPL") or "0")
            balance = Decimal(data.get("totalWalletBalance") or "0")
        except Exception:
            logger.warning("Invalid WS wallet data for account %s", account_id)
            return

        # Debounce DB query: fetch rules at most once per 1.5s regardless of path
        now = time.monotonic()
        last = self._last_ws_eval.get(account_id, 0.0)
        if (now - last) >= self._ws_debounce_interval or account_id not in self._rules_cache:
            rules = await self._db.list_active_rules_for_account(account_id)
            self._rules_cache[account_id] = rules
            self._last_ws_eval[account_id] = now
        else:
            rules = self._rules_cache.get(account_id)

        if not rules:
            return

        equity_rules = [r for r in rules if r["trigger_type"] not in ("BREAKEVEN_TIMEOUT", "MAX_DURATION", "TRAILING_PROFIT", "PAUSE_TRADING")]
        if not equity_rules:
            return

        # Split: drawdown rules get zero debounce, others wait for debounce interval
        drawdown_rules = [r for r in equity_rules if r["trigger_type"] in ("EQUITY_DROP_PCT", "EQUITY_DROP_PCT_SMART")]
        other_rules = [r for r in equity_rules if r["trigger_type"] not in ("EQUITY_DROP_PCT", "EQUITY_DROP_PCT_SMART")]

        # Evaluate drawdown rules immediately (no debounce, skip if lock held)
        if drawdown_rules:
            lock = self._ws_eval_locks.setdefault(account_id, asyncio.Lock())
            if not lock.locked():
                async with lock:
                    await self._evaluate_account_rules_with_data(account_id, drawdown_rules, equity, pnl, balance)

        # Evaluate other rules only when debounce has passed (use same debounce timestamp)
        if other_rules and (now - last) >= self._ws_debounce_interval:
            lock = self._ws_eval_locks.setdefault(account_id, asyncio.Lock())
            if not lock.locked():
                async with lock:
                    await self._evaluate_account_rules_with_data(account_id, other_rules, equity, pnl, balance)

    async def _evaluate_account_rules(self, account_id: str, rules: list[dict]) -> None:
        trailing_rules = [r for r in rules if r["trigger_type"] == "TRAILING_PROFIT"]
        other_rules = [r for r in rules if r["trigger_type"] not in ("TRAILING_PROFIT", "PAUSE_TRADING")]

        if trailing_rules:
            await self._evaluate_trailing_profit(account_id, trailing_rules)

        if not other_rules:
            return

        try:
            wallet = await self._accounts_service.get_wallet(account_id)
        except Exception:
            logger.warning("Cannot fetch wallet for account %s, skipping rules", account_id)
            return

        try:
            equity = Decimal(wallet.get("totalEquity") or "0")
            pnl = Decimal(wallet.get("totalPerpUPL") or "0")
            balance = Decimal(wallet.get("totalWalletBalance") or "0")
        except Exception:
            logger.warning("Invalid wallet data for account %s, skipping rules", account_id)
            return

        await self._evaluate_account_rules_with_data(account_id, other_rules, equity, pnl, balance)

    async def _evaluate_account_rules_with_data(
        self, account_id: str, rules: list[dict], equity: Decimal, pnl: Decimal, balance: Decimal
    ) -> None:
        logger.debug(
            "Account %s wallet: equity=%s, balance=%s, pnl=%s, rules=%d",
            account_id, equity, balance, pnl, len(rules),
        )

        for rule in rules:
            try:
                triggered = self._check_condition(rule, equity=equity, pnl=pnl, balance=balance)
                if triggered:
                    logger.info(
                        "Rule %s triggered for account %s (type=%s, threshold=%s)",
                        rule["id"], account_id, rule["trigger_type"], rule["threshold_value"],
                    )
                    did_transition = await self._db.atomic_trigger_rule(rule["id"])
                    if not did_transition:
                        continue

                    # BREAKEVEN_TIMEOUT: modify TP instead of closing
                    if rule["trigger_type"] == "BREAKEVEN_TIMEOUT":
                        # Skip if symbol is actively trailing — reset back to active
                        trailing_symbols = self._get_active_trailing()
                        rule_symbol = rule.get("symbol", "")
                        if rule_symbol in trailing_symbols:
                            logger.info("Skipping BREAKEVEN_TIMEOUT rule %s — symbol %s actively trailing, resetting to active", rule["id"], rule_symbol)
                            await self._db.update_close_rule(rule["id"], status="active")
                            continue
                        try:
                            await self._handle_breakeven_timeout(account_id, rule)
                            await self._db.update_close_rule(rule["id"], status="executed")
                            self._rule_failures.pop(rule["id"], None)
                            logger.info("Breakeven timeout rule %s executed for account %s", rule["id"], account_id)
                        except Exception:
                            logger.exception("Breakeven timeout handler failed for rule %s", rule["id"])
                            await self._db.update_close_rule(rule["id"], status="active")
                        continue
                    try:
                        close_kwargs: dict[str, Any] = {}
                        if rule.get("cycle_id") and self._cycle_repo:
                            try:
                                close_kwargs["symbols"] = await self._cycle_repo.get_cycle_trade_symbols(rule["cycle_id"])
                            except Exception:
                                logger.warning("Failed to get cycle trade symbols for rule %s, closing all", rule["id"])
                        if rule["trigger_type"] == "EQUITY_DROP_PCT_SMART":
                            try:
                                positions = await self._accounts_service.get_positions(account_id)
                                losing_symbols = [
                                    p.get("symbol") for p in (positions or [])
                                    if p.get("symbol") and float(p.get("unrealisedPnl", p.get("unrealized_pnl", 0)) or 0) < 0
                                ]
                                if losing_symbols:
                                    close_kwargs["symbols"] = losing_symbols
                                else:
                                    # No losers: reset reference to current equity to prevent
                                    # immediate re-trigger. Note: this can only lower the reference
                                    # when equity dropped without any single position being negative
                                    # (e.g., after a previous SMART close realized losses).
                                    logger.info("Smart drawdown rule %s: no losing positions, resetting baseline to %.2f", rule["id"], float(equity))
                                    await self._db.update_close_rule(rule["id"], status="active", reference_value=str(equity))
                                    continue
                            except Exception:
                                logger.warning("Smart drawdown: failed to get positions for %s, closing all", account_id)
                        result = await self._close_service.close_all_for_rule(account_id, rule["id"], **close_kwargs)
                        if result.get("skipped"):
                            logger.info("Close skipped for rule %s (concurrent close), reverting to active", rule["id"])
                            await self._db.update_close_rule(rule["id"], status="active")
                        elif result.get("failed", 0) > 0 and result.get("closed", 0) == 0:
                            logger.warning("Rule %s: all closes failed (%d), reverting to active for retry", rule["id"], result["failed"])
                            await self._db.update_close_rule(rule["id"], status="active")
                        else:
                            if result.get("failed", 0) > 0:
                                logger.warning("Rule %s: partial close — %d closed, %d failed for account %s", rule["id"], result.get("closed", 0), result["failed"], account_id)
                            logger.info("Rule %s executed, transitioning to 'executed'", rule["id"])
                            await self._db.update_close_rule(rule["id"], status="executed")
                            self._rule_failures.pop(rule["id"], None)
                            if rule["trigger_type"] != "EQUITY_DROP_PCT_SMART":
                                cleared = await self._db.deactivate_rules_for_account(account_id, exclude_rule_id=rule["id"])
                                if cleared:
                                    logger.info("Deactivated %d remaining rules for account %s after rule %s executed", cleared, account_id, rule["id"])
                            if self._cycle_callback and rule.get("cycle_id"):
                                try:
                                    await self._cycle_callback(rule)
                                except Exception:
                                    logger.exception("Cycle callback failed for rule %s", rule["id"])
                            if rule["trigger_type"] != "EQUITY_DROP_PCT_SMART":
                                break  # all other rules deactivated, stop evaluating this account
                    except asyncio.CancelledError:
                        logger.warning("Close cancelled (timeout) for rule %s, reverting to active", rule["id"])
                        await self._db.update_close_rule(rule["id"], status="active")
                        raise
                    except Exception:
                        rule_id = rule["id"]
                        self._rule_failures[rule_id] = self._rule_failures.get(rule_id, 0) + 1
                        if self._rule_failures[rule_id] >= MAX_RULE_FAILURES:
                            logger.error("Rule %s failed %d times, pausing", rule_id, self._rule_failures[rule_id])
                            await self._db.update_close_rule(rule_id, status="paused")
                            self._rule_failures.pop(rule_id, None)
                        else:
                            logger.exception("Failed to close positions for rule %s (attempt %d), reverting to active", rule_id, self._rule_failures[rule_id])
                            await self._db.update_close_rule(rule_id, status="active")
            except Exception:
                logger.exception("Error evaluating rule %s", rule["id"])

    def _check_condition(
        self,
        rule: dict,
        equity: Decimal,
        pnl: Decimal,
        balance: Decimal,
    ) -> bool:
        trigger_type = rule["trigger_type"]

        # Time-based rules: check elapsed time, don't parse reference as Decimal
        if trigger_type in ("BREAKEVEN_TIMEOUT", "MAX_DURATION"):
            return self._check_time_elapsed(rule)

        # TRAILING_PROFIT handled separately in _evaluate_trailing_profit
        if trigger_type == "TRAILING_PROFIT":
            return False

        threshold = Decimal(rule["threshold_value"])
        reference = Decimal(rule["reference_value"]) if rule.get("reference_value") else None

        if trigger_type == "BALANCE_BELOW":
            return equity <= threshold
        elif trigger_type == "BALANCE_ABOVE":
            return equity >= threshold
        elif trigger_type == "PNL_BELOW":
            return pnl <= -threshold
        elif trigger_type == "PNL_ABOVE":
            return pnl >= threshold
        elif trigger_type in ("EQUITY_DROP_PCT", "EQUITY_DROP_PCT_SMART"):
            if not reference or reference == 0:
                return False
            drop_pct = ((reference - equity) / reference) * Decimal("100")
            return drop_pct >= threshold
        elif trigger_type == "EQUITY_RISE_PCT":
            if not reference or reference == 0:
                return False
            rise_pct = ((equity - reference) / reference) * Decimal("100")
            return rise_pct >= threshold

        logger.warning("unknown_trigger_type", extra={"trigger_type": trigger_type, "rule_id": rule.get("id")})
        return False

    async def _evaluate_trailing_profit(self, account_id: str, rules: list[dict]) -> None:
        """Per-position trailing stop: close individual positions that drop from peak profit."""
        try:
            positions = await self._accounts_service.get_positions(account_id)
        except Exception:
            logger.debug("Cannot fetch positions for trailing profit eval, account %s", account_id)
            return
        if not positions:
            return

        account_peaks = self._trailing_peaks.setdefault(account_id, {})
        _TRAIL_RATIO = 0.5  # Close when profit drops below 50% of peak
        actively_trailing = self._get_active_trailing()

        for rule in rules:
            activation_pct = float(rule.get("threshold_value", 2.0))
            for pos in positions:
                symbol = pos.get("symbol", "")
                if not symbol or symbol in actively_trailing:
                    continue
                upnl = float(pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0)) or 0)
                entry_price = float(pos.get("avgPrice", 0) or 0)
                mark_price = float(pos.get("markPrice", 0) or 0)
                size = float(pos.get("size", 0) or 0)
                if entry_price <= 0 or mark_price <= 0 or size <= 0:
                    continue

                profit_pct = abs(mark_price - entry_price) / entry_price * 100
                if upnl <= 0:
                    account_peaks.pop(symbol, None)
                    continue
                if profit_pct < activation_pct:
                    continue  # Profitable but below activation — don't clear peak

                # Track per-unit PnL to be immune to partial closes by user
                per_unit_pnl = upnl / size
                prev_peak = account_peaks.get(symbol, 0.0)
                # Guard against stale peaks from pre-migration data (absolute $ vs per-unit)
                # If peak is >100x current per_unit, it's clearly stale data — reset
                if prev_peak > 0 and per_unit_pnl > 0 and prev_peak > per_unit_pnl * 100:
                    account_peaks[symbol] = per_unit_pnl
                    continue
                if per_unit_pnl > prev_peak:
                    account_peaks[symbol] = per_unit_pnl
                    continue

                peak = account_peaks[symbol]
                if peak > 0 and per_unit_pnl < peak * _TRAIL_RATIO:
                    logger.info(
                        "Trailing profit triggered for %s on account %s: per_unit=$%.4f, peak=$%.4f",
                        symbol, account_id, per_unit_pnl, peak,
                    )
                    try:
                        await self._close_service.close_all_for_rule(
                            account_id, rule["id"], symbols=[symbol]
                        )
                        account_peaks.pop(symbol, None)
                    except Exception:
                        logger.exception("Failed to close %s via trailing profit", symbol)

        # Prune peaks for positions that no longer exist
        current_symbols = {p.get("symbol") for p in positions}
        stale = [s for s in account_peaks if s not in current_symbols]
        for s in stale:
            del account_peaks[s]

    def _check_time_elapsed(self, rule: dict) -> bool:
        """Check if elapsed time since reference_value exceeds threshold_value hours."""
        try:
            ref_str = rule.get("reference_value", "")
            threshold_hours = float(rule["threshold_value"])
            start_time = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            elapsed_hours = (datetime.now(timezone.utc) - start_time).total_seconds() / 3600
            return elapsed_hours >= threshold_hours
        except (ValueError, TypeError):
            logger.warning("invalid_time_rule_data", extra={"rule_id": rule.get("id")})
            return False

    async def _handle_breakeven_timeout(self, account_id: str, rule: dict) -> None:
        """Move all positions' TP to breakeven (1% unrealised PnL to cover fees)."""
        try:
            client = await self._accounts_service.get_client(account_id)
            positions = await client.get_positions()
            if not positions:
                return
            for pos in positions:
                try:
                    symbol = pos.get("symbol", "")
                    side = pos.get("side", "")
                    avg_price = float(pos.get("avgPrice") or pos.get("entryPrice") or "0")
                    leverage = float(pos.get("leverage") or "1")
                    if avg_price <= 0:
                        continue

                    # Calculate breakeven TP: 1% profit on leveraged position using Decimal
                    avg_price_dec = Decimal(str(avg_price))
                    leverage_dec = Decimal(str(leverage))
                    price_move_pct = Decimal("1.0") / leverage_dec

                    if side == "Buy":
                        new_tp_dec = avg_price_dec * (Decimal("1") + price_move_pct / Decimal("100"))
                    elif side == "Sell":
                        new_tp_dec = avg_price_dec * (Decimal("1") - price_move_pct / Decimal("100"))
                    else:
                        continue

                    # Fetch instrument info to get tickSize
                    try:
                        instrument = await client.get_instrument_info(symbol)
                        price_filter = instrument.get("priceFilter", {})
                        tick_size_str = price_filter.get("tickSize")
                    except Exception:
                        tick_size_str = None

                    if tick_size_str:
                        tick_size = Decimal(tick_size_str)
                        rounded_tp = (new_tp_dec / tick_size).quantize(Decimal("1"), rounding=ROUND_DOWN) * tick_size
                        new_tp = str(rounded_tp)
                    else:
                        new_tp = str(round(new_tp_dec, 6))

                    await client.set_trading_stop(
                        symbol=symbol,
                        take_profit=new_tp,
                        position_idx=int(pos.get("positionIdx", 0)),
                    )
                    logger.info("breakeven_tp_set", extra={
                        "account_id": account_id, "symbol": symbol,
                        "side": side, "new_tp": new_tp,
                    })
                except Exception:
                    logger.warning("breakeven_tp_set_failed", extra={
                        "account_id": account_id, "symbol": pos.get("symbol"),
                    }, exc_info=True)
        except Exception:
            logger.exception("breakeven_timeout_handler_failed", extra={"account_id": account_id})
