"""Auto-trade execution service for market scans."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.ai_manager_schemas import AIManagerConfig as _AIMConfig
from backend.services.sector_map import get_sector as _static_get_sector


logger = logging.getLogger(__name__)


def _to_symbol(ticker: str) -> str:
    """Normalise a ticker to a USDT-margined symbol."""
    return ticker if ticker.endswith("USDT") else f"{ticker}USDT"


def _sanitize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    bad = ("key", "secret", "token", "password")
    return {k: v for k, v in cfg.items() if not any(b in k.lower() for b in bad)}


@dataclass
class TradeExecution:
    account_id: str
    symbol: str
    side: str
    status: str  # "success" | "failed"
    order_id: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class AutoTradeExecutor:
    """Evaluates scan results against auto-trade configs and executes trades."""

    def __init__(self, accounts_service: Any, close_positions_service: Any = None, ai_manager_service: Any = None, sector_service: Any = None, *, recorder: Any = None, debug_ctx: Any = None):
        self._accounts = accounts_service
        self._close_svc = close_positions_service
        self._ai_manager_service = ai_manager_service
        self._sector_service = sector_service
        self._state: Dict[str, _AccountState] = {}
        self._lock = asyncio.Lock()
        self._ai_manager_enabled_accounts: set = set()
        self._recorder = recorder
        self._debug_ctx = debug_ctx

    def _emit_life(self, account_id: str, phase: str, event_type: str, **detail: Any) -> None:
        """Fail-open lifecycle emit helper. Never raises, never blocks."""
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        rec.emit_lifecycle(ctx, account_id=account_id, phase=phase, event_type=event_type, detail=detail or {})

    def _emit_snapshot(self, account_id: str, gate: str, positions, wallet=None, equity=None) -> None:
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        rec.emit_exchange_snapshot(ctx, account_id=account_id, gate=gate, positions=positions, wallet=wallet, equity=equity)

    def _emit_decision(self, account_id: str, phase: str, symbol: str, decision: str, reason_code: str, result: Dict[str, Any], **detail: Any) -> None:
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return
        rec.emit_symbol_decision(
            ctx, account_id=account_id, phase=phase, symbol=symbol,
            decision=decision, reason_code=reason_code, reason_detail=detail or {},
            scan_score=result.get("score"), scan_confidence=result.get("confidence"),
            scan_direction=result.get("direction"),
        )

    def init_configs(self, configs: List[Dict[str, Any]]) -> None:
        self._state.clear()
        for i, cfg in enumerate(configs):
            key = f"{cfg['account_id']}_{i}"
            self._state[key] = _AccountState(config=cfg)

    def restore_state(self, prior_results: List[Dict[str, Any]]) -> None:
        """Restore trade counters and execution records from previously executed auto_trade_results (for resume)."""
        account_success: Dict[str, int] = {}
        account_failed: Dict[str, int] = {}
        account_executions: Dict[str, List[TradeExecution]] = {}
        for r in prior_results:
            aid = r.get("account_id", "")
            if r.get("status") == "success":
                account_success[aid] = account_success.get(aid, 0) + 1
            else:
                account_failed[aid] = account_failed.get(aid, 0) + 1
            account_executions.setdefault(aid, []).append(TradeExecution(
                account_id=aid,
                symbol=r.get("symbol", ""),
                side=r.get("side", ""),
                status=r.get("status", "failed"),
                order_id=r.get("order_id"),
                error=r.get("error"),
            ))
        for state in self._state.values():
            aid = state.config["account_id"]
            state.trades_executed = account_success.get(aid, 0)
            state.trades_failed = account_failed.get(aid, 0)
            state.executions = list(account_executions.get(aid, []))

    async def init_balances(self) -> None:
        """Pre-fetch wallet balances and check positions for all configured accounts."""
        rules_created_for: set = set()  # track accounts that already got close rules this cycle
        force_closed_accounts: set = set()  # track accounts already force-closed this cycle
        positions_cache: Dict[str, list] = {}  # account_id -> positions list (avoid re-fetching)
        emitted_scan_start: set = set()  # accounts that already got a scan_start snapshot emit
        marked_stopped_for: set = set()  # accounts already emitted a marked_stopped lifecycle

        # Pre-pass: force-close accounts where unrealized PnL has reached X% of the target goal
        # close_on_profit_pct = percentage of target_goal_value achieved (e.g., 50 means close at 50% of target)
        accounts_with_close_target: Dict[str, tuple] = {}  # account_id -> (close_pct, target_goal_value)
        for state in self._state.values():
            aid = state.config.get("account_id", "")
            close_pct = state.config.get("close_on_profit_pct")
            target_goal = state.config.get("target_goal_value")
            if close_pct and target_goal and aid and aid not in accounts_with_close_target:
                accounts_with_close_target[aid] = (close_pct, target_goal)

        for account_id, (close_pct, target_goal) in accounts_with_close_target.items():
            if not self._close_svc:
                break
            try:
                wallet = await self._accounts.get_wallet(account_id)
                equity = float(wallet.get("totalEquity") or "0")
                if equity <= 0:
                    continue

                # Use the reference_value from the existing EQUITY_RISE_PCT rule as the base,
                # since the target_goal% was set relative to that balance (from the previous scan).
                # This ensures the threshold is consistent regardless of wallet balance changes.
                reference_balance = 0.0
                try:
                    existing_rules = await self._close_svc.list_rules(account_id)
                    for rule in existing_rules:
                        if rule.get("trigger_type") == "EQUITY_RISE_PCT" and rule.get("status") == "active":
                            ref_val = rule.get("reference_value")
                            if ref_val:
                                reference_balance = float(ref_val)
                                break
                except Exception:
                    pass

                # Fall back to current wallet balance if no existing rule reference found
                if reference_balance <= 0:
                    reference_balance = float(wallet.get("totalWalletBalance") or "0")

                if reference_balance > 0:
                    # Use equity rise % (same formula as close_rule_evaluator) to include
                    # both realized and unrealized PnL since the scan started
                    pnl_pct = ((equity - reference_balance) / reference_balance) * 100
                    if pnl_pct <= 0:
                        continue
                    # Threshold = close_pct% of the target_goal equity rise
                    effective_threshold = (close_pct / 100) * target_goal
                    if pnl_pct >= effective_threshold:
                        logger.info("auto_trade_force_close_triggered", extra={
                            "account_id": account_id, "pnl_pct": round(pnl_pct, 2),
                            "effective_threshold": round(effective_threshold, 2),
                            "close_pct": close_pct, "target_goal": target_goal,
                            "reference_balance": round(reference_balance, 2),
                        })
                        await self._close_svc.close_all_positions(account_id)
                        await asyncio.sleep(2)
                        force_closed_accounts.add(account_id)
            except Exception as e:
                logger.warning("auto_trade_close_on_profit_check_failed", extra={"account_id": account_id, "error": str(e)[:200]})

        account_valid_cache: Dict[str, bool] = {}

        for key, state in self._state.items():
            if state.stopped:
                continue
            account_id = state.config["account_id"]
            if not account_id:
                state.stopped = True
                state.stopped_reason = "no_account_id"
                continue
            # Validate account still exists (not soft-deleted)
            if account_id not in account_valid_cache:
                try:
                    acct = await self._accounts.get_account(account_id)
                    account_valid_cache[account_id] = acct is not None
                except Exception as e:
                    account_valid_cache[account_id] = False
                    logger.warning("auto_trade_account_check_failed", extra={"account_id": account_id, "error": str(e)[:200]})
            if not account_valid_cache[account_id]:
                state.stopped = True
                state.stopped_reason = "account_deleted"
                logger.warning("auto_trade_account_deleted", extra={"account_id": account_id})
                continue
            # Check for AI PAUSE_TRADING rule
            if self._close_svc:
                try:
                    active_rules = await self._close_svc.list_rules(account_id)
                    for rule in active_rules:
                        if rule.get("trigger_type") == "PAUSE_TRADING" and rule.get("status") == "active":
                            ref_str = rule.get("reference_value", "")
                            hours = float(rule.get("threshold_value", 0))
                            try:
                                ref_time = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
                                if (datetime.now(timezone.utc) - ref_time).total_seconds() < hours * 3600:
                                    state.stopped = True
                                    state.stopped_reason = "ai_paused_trading"
                                    break
                                else:
                                    await self._close_svc.delete_rule(account_id, rule["id"])
                            except (ValueError, TypeError):
                                # Fail-closed: unparseable pause rule = stay paused (safety)
                                state.stopped = True
                                state.stopped_reason = "ai_paused_trading"
                                logger.warning("pause_rule_unparseable_fail_closed", extra={"account_id": account_id, "ref": ref_str[:50]})
                                break
                except Exception as e:
                    logger.debug("pause_trading_check_failed", extra={"account_id": account_id, "error": str(e)[:200]})
            if state.stopped:
                continue
            # Check positions if skip_if_positions_open is enabled
            if state.config.get("skip_if_positions_open") and account_id not in force_closed_accounts:
                if account_id in positions_cache:
                    positions = positions_cache[account_id]
                else:
                    try:
                        positions = await self._accounts.get_positions(account_id)
                        positions_cache[account_id] = positions
                    except Exception as e:
                        positions = []
                        logger.warning("auto_trade_position_check_failed", extra={"account_id": account_id, "error": str(e)[:512]})
                if positions:
                    state.stopped = True
                    state.stopped_reason = "positions_already_open"
                    logger.info("auto_trade_skipped_positions", extra={"account_id": account_id, "position_count": len(positions)})
                    if account_id not in marked_stopped_for:
                        marked_stopped_for.add(account_id)
                        if account_id not in emitted_scan_start:
                            emitted_scan_start.add(account_id)
                            self._emit_snapshot(account_id, "scan_start", positions)
                        self._emit_life(account_id, "init_balances", "marked_stopped",
                                        reason="positions_already_open", position_count=len(positions))
                    continue
            # Fetch and lock balance for this cycle
            try:
                wallet = await self._accounts.get_wallet(account_id)
                balance_str = wallet.get("totalAvailableBalance") or wallet.get("totalWalletBalance") or "0"
                state.base_capital = float(balance_str)
            except Exception as e:
                state.stopped = True
                state.stopped_reason = f"wallet_fetch_failed: {str(e)[:200]}"
                logger.warning("auto_trade_init_balance_failed", extra={"account_id": account_id, "error": str(e)[:512]})
                continue
            if state.base_capital <= 0:
                state.stopped = True
                state.stopped_reason = "zero_balance"
                continue
            # Record existing position symbols to avoid opening trades on symbols already held
            if account_id not in force_closed_accounts:
                if account_id not in positions_cache:
                    try:
                        positions_cache[account_id] = await self._accounts.get_positions(account_id)
                    except Exception:
                        positions_cache[account_id] = []
                state.existing_symbols = {p.get("symbol", "") for p in positions_cache[account_id]}
                state.position_directions = {
                    p.get("symbol", ""): ("short" if p.get("side", "").lower() == "sell" else "long")
                    for p in positions_cache[account_id] if p.get("symbol")
                }
                if account_id not in emitted_scan_start:
                    emitted_scan_start.add(account_id)
                    self._emit_snapshot(account_id, "scan_start", positions_cache[account_id], equity=state.base_capital)
            # Create close rules (only once per account per cycle)
            if account_id not in rules_created_for and state.base_capital > 0:
                # Create new rules FIRST, then delete old ones (avoids unprotected window)
                # Profit target rule
                if state.config.get("target_goal_type") == "profit_pct" and self._close_svc:
                    goal_value = state.config.get("target_goal_value")
                    if goal_value and goal_value > 0:
                        try:
                            rule = await self._close_svc.create_rule(
                                account_id=account_id,
                                rule_data={
                                    "trigger_type": "EQUITY_RISE_PCT",
                                    "threshold_value": str(goal_value),
                                    "reference_value": str(state.base_capital),
                                },
                            )
                            state.close_rule_id = rule.get("id")
                            state.created_rule_ids.append(rule.get("id"))
                            logger.info("auto_trade_close_rule_created", extra={"account_id": account_id, "rule_id": state.close_rule_id, "threshold": goal_value})
                        except Exception as e:
                            state.stopped = True
                            state.stopped_reason = "profit_rule_creation_failed"
                            logger.warning("auto_trade_close_rule_failed", extra={"account_id": account_id, "error": str(e)[:512]})
                            continue
                # Max drawdown rule
                max_drawdown = state.config.get("max_drawdown_pct", 100)
                if max_drawdown < 100 and self._close_svc:
                    try:
                        _drawdown_type = "EQUITY_DROP_PCT_SMART" if state.config.get("smart_drawdown_close") else "EQUITY_DROP_PCT"
                        rule = await self._close_svc.create_rule(
                            account_id=account_id,
                            rule_data={
                                "trigger_type": _drawdown_type,
                                "threshold_value": str(max_drawdown),
                                "reference_value": str(state.base_capital),
                            },
                        )
                        state.drawdown_rule_id = rule.get("id")
                        state.created_rule_ids.append(rule.get("id"))
                        logger.info("auto_trade_drawdown_rule_created", extra={"account_id": account_id, "rule_id": state.drawdown_rule_id, "threshold": max_drawdown})
                    except Exception as e:
                        state.stopped = True
                        state.stopped_reason = "drawdown_rule_creation_failed"
                        logger.warning("auto_trade_drawdown_rule_failed", extra={"account_id": account_id, "error": str(e)[:512]})
                        continue
                # Breakeven timeout rule (move TP to breakeven after X hours)
                breakeven_hours = state.config.get("breakeven_timeout_hours")
                if breakeven_hours and breakeven_hours > 0 and self._close_svc:
                    from datetime import datetime, timezone as tz
                    try:
                        rule = await self._close_svc.create_rule(
                            account_id=account_id,
                            rule_data={
                                "trigger_type": "BREAKEVEN_TIMEOUT",
                                "threshold_value": str(breakeven_hours),
                                "reference_value": datetime.now(tz.utc).isoformat(),
                            },
                        )
                        state.created_rule_ids.append(rule.get("id"))
                        logger.info("auto_trade_breakeven_timeout_rule_created", extra={"account_id": account_id, "hours": breakeven_hours})
                    except Exception as e:
                        logger.warning("auto_trade_breakeven_timeout_rule_failed", extra={"account_id": account_id, "error": str(e)[:200]})
                # Max trade duration rule (force close all after X hours)
                max_duration_hours = state.config.get("max_trade_duration_hours")
                if max_duration_hours and max_duration_hours > 0 and self._close_svc:
                    from datetime import datetime, timezone as tz
                    try:
                        rule = await self._close_svc.create_rule(
                            account_id=account_id,
                            rule_data={
                                "trigger_type": "MAX_DURATION",
                                "threshold_value": str(max_duration_hours),
                                "reference_value": datetime.now(tz.utc).isoformat(),
                            },
                        )
                        state.created_rule_ids.append(rule.get("id"))
                        logger.info("auto_trade_max_duration_rule_created", extra={"account_id": account_id, "hours": max_duration_hours})
                    except Exception as e:
                        logger.warning("auto_trade_max_duration_rule_failed", extra={"account_id": account_id, "error": str(e)[:200]})
                # Trailing profit rule (per-position trailing stop)
                trailing_pct = state.config.get("trailing_profit_pct")
                if trailing_pct and trailing_pct > 0 and self._close_svc:
                    try:
                        rule = await self._close_svc.create_rule(
                            account_id=account_id,
                            rule_data={
                                "trigger_type": "TRAILING_PROFIT",
                                "threshold_value": str(trailing_pct),
                                "reference_value": "0",
                            },
                        )
                        state.created_rule_ids.append(rule.get("id"))
                        logger.info("auto_trade_trailing_profit_rule_created", extra={"account_id": account_id, "pct": trailing_pct})
                    except Exception as e:
                        logger.warning("auto_trade_trailing_profit_rule_failed", extra={"account_id": account_id, "error": str(e)[:200]})
                # Now delete old rules (new ones are already active, no unprotected gap)
                if self._close_svc and state.created_rule_ids:
                    try:
                        new_ids = {rid for rid in state.created_rule_ids if rid}
                        old_rules = await self._close_svc.list_rules(account_id)
                        for old_rule in old_rules:
                            if old_rule.get("id") not in new_ids and old_rule.get("trigger_type") != "PAUSE_TRADING":
                                try:
                                    await self._close_svc.delete_rule(account_id, old_rule["id"])
                                except Exception:
                                    pass
                    except Exception:
                        logger.debug("auto_trade_cleanup_old_rules_failed", extra={"account_id": account_id})
                rules_created_for.add(account_id)
                self._emit_life(account_id, "init_balances", "rules_created", rule_ids=list(state.created_rule_ids))

        # Propagate rule IDs and base_capital to sibling configs sharing the same account
        account_rule_map: Dict[str, tuple] = {}
        for state in self._state.values():
            aid = state.config["account_id"]
            if state.close_rule_id or state.drawdown_rule_id or state.base_capital or state.created_rule_ids:
                if aid not in account_rule_map:
                    account_rule_map[aid] = (state.close_rule_id, state.drawdown_rule_id, state.base_capital, list(state.created_rule_ids))
                else:
                    existing = account_rule_map[aid]
                    merged_rules = list(set(existing[3] + state.created_rule_ids))
                    account_rule_map[aid] = (
                        state.close_rule_id or existing[0],
                        state.drawdown_rule_id or existing[1],
                        state.base_capital or existing[2],
                        merged_rules,
                    )
        for state in self._state.values():
            aid = state.config["account_id"]
            if aid in account_rule_map:
                cr, dr, bc, rids = account_rule_map[aid]
                if not state.close_rule_id and cr:
                    state.close_rule_id = cr
                if not state.drawdown_rule_id and dr:
                    state.drawdown_rule_id = dr
                if state.base_capital is None and bc:
                    state.base_capital = bc
                state.created_rule_ids = list(rids)

    async def evaluate_result(self, result: Dict[str, Any]) -> List[TradeExecution]:
        """Evaluate one scan result against all 'immediate' mode configs. Returns executions."""
        async with self._lock:
            executions: List[TradeExecution] = []
            traded_accounts: set = set()
            for key, state in self._state.items():
                if state.config.get("execution_mode") != "immediate":
                    continue
                if state.stopped:
                    continue
                account_id = state.config.get("account_id", "")
                if account_id in traded_accounts:
                    state.trades_skipped += 1
                    continue
                execution = await self._try_trade(state, result, phase="immediate")
                if execution and execution.status == "success":
                    traded_accounts.add(account_id)
                if execution:
                    executions.append(execution)
            return executions

    async def execute_batch(self, results: List[Dict[str, Any]]) -> List[TradeExecution]:
        """Execute all 'batch' mode configs against full results set (deduplicated by ticker)."""
        async with self._lock:
            # Deduplicate results by ticker — keep the latest (last in list)
            seen: Dict[str, Dict[str, Any]] = {}
            for r in results:
                ticker = r.get("ticker", "")
                if ticker:
                    seen[ticker] = r
            unique_results = sorted(
                list(seen.values()),
                key=lambda r: (abs(r.get("score", 0)), r.get("completed_at", "")),
                reverse=True,
            )

            executions: List[TradeExecution] = []
            traded: set = set()  # (account_id, ticker) pairs already traded
            for key, state in self._state.items():
                if state.config.get("execution_mode") != "batch":
                    continue
                account_id = state.config.get("account_id", "")
                for result in unique_results:
                    if state.stopped:
                        break
                    ticker = result.get("ticker", "")
                    trade_key = (account_id, ticker)
                    if trade_key in traded:
                        state.trades_skipped += 1
                        continue
                    execution = await self._try_trade(state, result, phase="batch")
                    if execution and execution.status == "success":
                        traded.add(trade_key)
                    if execution:
                        executions.append(execution)

            # Fill pass: if fill_to_max_trades is enabled and max_trades not reached,
            # retry with relaxed filters using best remaining signals by score
            for key, state in self._state.items():
                if state.config.get("execution_mode") != "batch":
                    continue
                if not state.config.get("fill_to_max_trades"):
                    continue
                if state.stopped and state.stopped_reason != "max_trades_reached":
                    continue
                max_trades = state.config.get("max_trades", 999)
                remaining_slots = max_trades - state.trades_executed
                if remaining_slots <= 0:
                    continue

                account_id = state.config.get("account_id", "")
                # Sort remaining signals by abs(score) descending
                fill_candidates = sorted(
                    [r for r in unique_results
                     if r.get("ticker") and (account_id, r["ticker"]) not in traded
                     and r.get("direction", "hold") != "hold"
                     and r.get("status") == "completed"],
                    key=lambda r: abs(r.get("score", 0)),
                    reverse=True,
                )

                # Reset stopped flag if it was set due to max_trades during strict pass
                if state.stopped and state.stopped_reason == "max_trades_reached":
                    state.stopped = False
                    state.stopped_reason = None

                for result in fill_candidates[:remaining_slots]:
                    if state.stopped:
                        break
                    ticker = result.get("ticker", "")
                    trade_key = (account_id, ticker)
                    if trade_key in traded:
                        continue
                    execution = await self._try_trade(state, result, relaxed=True, phase="fill")
                    if execution and execution.status == "success":
                        traded.add(trade_key)
                    if execution:
                        executions.append(execution)

            return executions

    async def fill_immediate_remaining(self, results: List[Dict[str, Any]]) -> List[TradeExecution]:
        """For immediate-mode configs with fill_to_max_trades, backfill from all results after scan completes."""
        async with self._lock:
            seen: Dict[str, Dict[str, Any]] = {}
            for r in results:
                ticker = r.get("ticker", "")
                if ticker:
                    seen[ticker] = r
            unique_results = list(seen.values())

            executions: List[TradeExecution] = []
            traded: set = set()  # (account_id, symbol) cross-config deduplication

            # Pre-populate traded set from strict-pass executions
            for state in self._state.values():
                if state.config.get("execution_mode") != "immediate":
                    continue
                aid = state.config.get("account_id", "")
                for e in state.executions:
                    if e.status == "success":
                        traded.add((aid, e.symbol))

            for key, state in self._state.items():
                if state.config.get("execution_mode") != "immediate":
                    continue
                if not state.config.get("fill_to_max_trades"):
                    continue
                max_trades = state.config.get("max_trades", 999)
                remaining_slots = max_trades - state.trades_executed
                if remaining_slots <= 0:
                    continue

                # Reset stopped flag if it was set during strict evaluation
                if state.stopped and state.stopped_reason == "max_trades_reached":
                    state.stopped = False
                    state.stopped_reason = None
                elif state.stopped:
                    continue

                account_id = state.config.get("account_id", "")

                fill_candidates = sorted(
                    [r for r in unique_results
                     if r.get("direction", "hold") != "hold"
                     and r.get("status") == "completed"
                     and r.get("ticker")
                     and (account_id, _to_symbol(r["ticker"])) not in traded],
                    key=lambda r: abs(r.get("score", 0)),
                    reverse=True,
                )

                for result in fill_candidates[:remaining_slots]:
                    if state.stopped:
                        break
                    ticker = result.get("ticker", "")
                    symbol = _to_symbol(ticker)
                    if (account_id, symbol) in traded:
                        continue
                    execution = await self._try_trade(state, result, relaxed=True, phase="fill")
                    if execution and execution.status == "success":
                        traded.add((account_id, symbol))
                    if execution:
                        executions.append(execution)

            return executions

    def get_summaries(self) -> List[Dict[str, Any]]:
        summaries = []
        for key, state in self._state.items():
            summaries.append({
                "account_id": state.config["account_id"],
                "trades_executed": state.trades_executed,
                "trades_failed": state.trades_failed,
                "trades_skipped": state.trades_skipped,
                "stopped_reason": state.stopped_reason,
                "close_rule_id": state.close_rule_id,
                "drawdown_rule_id": state.drawdown_rule_id,
                "executions": [
                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                     "order_id": e.order_id, "error": e.error}
                    for e in state.executions
                ],
            })
        return summaries

    async def emit_account_summaries(self) -> int:
        """Emit one account-trace per state. Returns the distinct account count.
        Safe to call even when tracing is off (returns the count without emitting)."""
        seen_accounts = {s.config.get("account_id", "") for s in self._state.values()}
        rec, ctx = self._recorder, self._debug_ctx
        if rec is None or ctx is None:
            return len(seen_accounts)
        label_cache: Dict[str, Optional[str]] = {}
        for state in self._state.values():
            aid = state.config.get("account_id", "")
            if aid and aid not in label_cache:
                try:
                    acct = await self._accounts.get_account(aid)
                    label_cache[aid] = (acct or {}).get("label")
                except Exception:
                    label_cache[aid] = None
            rec.emit_account_trace(
                ctx, account_id=aid,
                account_label=label_cache.get(aid),
                execution_mode=state.config.get("execution_mode"),
                final_stopped_reason=state.stopped_reason,
                gate_that_stopped=state.stopped_reason,
                rescued_by_recheck=getattr(state, "rescued_by_recheck", False),
                base_capital=state.base_capital,
                positions_at_start_count=len(state.existing_symbols),
                trades_executed=state.trades_executed,
                trades_failed=state.trades_failed,
                trades_skipped=state.trades_skipped,
                rules_created=[{"rule_id": r} for r in state.created_rule_ids],
                config_snapshot=_sanitize_config(state.config),
            )
        return len(seen_accounts)

    async def cleanup_unused_rules(self) -> None:
        """Delete close rules for accounts that had zero successful trades across ALL configs."""
        if not self._close_svc:
            return
        # Aggregate: did any config for this account execute successfully?
        account_has_trades: Dict[str, bool] = {}
        for state in self._state.values():
            aid = state.config["account_id"]
            if state.trades_executed > 0:
                account_has_trades[aid] = True
            elif aid not in account_has_trades:
                account_has_trades[aid] = False

        # Collect all rule IDs per account (deduplicated)
        account_rules: Dict[str, set] = {}
        for state in self._state.values():
            aid = state.config["account_id"]
            if aid not in account_rules:
                account_rules[aid] = set()
            if state.close_rule_id:
                account_rules[aid].add(state.close_rule_id)
            if state.drawdown_rule_id:
                account_rules[aid].add(state.drawdown_rule_id)
            for rid in state.created_rule_ids:
                if rid:
                    account_rules[aid].add(rid)

        # Delete rules only for accounts with zero total trades
        for aid, has_trades in account_has_trades.items():
            if has_trades:
                continue
            for rule_id in account_rules.get(aid, set()):
                try:
                    await self._close_svc.delete_rule(aid, rule_id)
                except Exception:
                    pass

    async def post_scan_recheck(self, results: List[Dict[str, Any]]) -> List[TradeExecution]:
        """Re-check accounts at end of scan for conditions that may have changed during the 2+ hour scan.

        This handles two scenarios:
        1. Accounts where close_on_profit_pct threshold is NOW met (PnL grew during scan)
           → close all positions, clear rules, then place new trades from scan results.
        2. Accounts that were skipped due to positions_already_open but positions have since
           closed (hit TP/SL/drawdown rule) → place new trades from scan results.
        """
        executions: List[TradeExecution] = []
        if not results:
            return executions

        # Deduplicate results by ticker — keep the latest
        seen: Dict[str, Dict[str, Any]] = {}
        for r in results:
            ticker = r.get("ticker", "")
            if ticker:
                seen[ticker] = r
        unique_results = sorted(
            list(seen.values()),
            key=lambda r: abs(r.get("score", 0)),
            reverse=True,
        )

        # Snapshot state under lock
        async with self._lock:
            accounts_to_recheck: Dict[str, List["_AccountState"]] = {}

            for state in self._state.values():
                aid = state.config.get("account_id", "")
                if not aid:
                    continue

                needs_recheck = False

                # Case 1: Account was skipped because positions were open
                if state.stopped and state.stopped_reason == "positions_already_open":
                    needs_recheck = True

                # Case 2: Account has close_on_profit_pct and may have reached threshold during scan
                close_pct = state.config.get("close_on_profit_pct")
                target_goal = state.config.get("target_goal_value")
                if close_pct and target_goal:
                    needs_recheck = True

                if needs_recheck:
                    accounts_to_recheck.setdefault(aid, []).append(state)

        if not accounts_to_recheck:
            return executions

        # Process each account outside the lock (network I/O)
        for account_id, states in accounts_to_recheck.items():
            try:
                # Check current positions
                positions = await self._accounts.get_positions(account_id)
                has_positions = bool(positions)
                self._emit_snapshot(account_id, "recheck", positions)
                self._emit_life(account_id, "post_scan_recheck", "recheck_entered", position_count=len(positions))

                # For accounts with close_on_profit_pct: check if threshold is met NOW
                force_closed = False
                any_close_pct = None
                any_target_goal = None
                for s in states:
                    cp = s.config.get("close_on_profit_pct")
                    tg = s.config.get("target_goal_value")
                    if cp and tg:
                        any_close_pct = cp
                        any_target_goal = tg
                        break

                if has_positions and any_close_pct and any_target_goal and self._close_svc:
                    wallet = await self._accounts.get_wallet(account_id)
                    equity = float(wallet.get("totalEquity") or "0")
                    if equity > 0:
                        # Get reference balance from existing rule
                        reference_balance = 0.0
                        try:
                            existing_rules = await self._close_svc.list_rules(account_id)
                            for rule in existing_rules:
                                if rule.get("trigger_type") == "EQUITY_RISE_PCT" and rule.get("status") == "active":
                                    ref_val = rule.get("reference_value")
                                    if ref_val:
                                        reference_balance = float(ref_val)
                                        break
                        except Exception:
                            pass
                        if reference_balance <= 0:
                            reference_balance = float(wallet.get("totalWalletBalance") or "0")

                        if reference_balance > 0:
                            pnl_pct = ((equity - reference_balance) / reference_balance) * 100
                            if pnl_pct <= 0:
                                pass  # no growth, skip close check
                            else:
                                effective_threshold = (any_close_pct / 100) * any_target_goal
                                if pnl_pct >= effective_threshold:
                                    logger.info("post_scan_force_close_triggered", extra={
                                        "account_id": account_id, "pnl_pct": round(pnl_pct, 2),
                                        "effective_threshold": round(effective_threshold, 2),
                                    })
                                    await self._close_svc.close_all_positions(account_id)
                                    await asyncio.sleep(2)
                                    force_closed = True
                                    has_positions = False

                # If account still has positions and wasn't force-closed, skip
                if has_positions and not force_closed:
                    self._emit_life(account_id, "post_scan_recheck", "recheck_positions_still_open")
                    continue

                # Account is now clear — reset states and place trades
                logger.info("post_scan_recheck_trading", extra={
                    "account_id": account_id, "force_closed": force_closed,
                    "reason": "positions_closed_during_scan",
                })

                # Refresh balance
                try:
                    wallet = await self._accounts.get_wallet(account_id)
                    balance_str = wallet.get("totalAvailableBalance") or wallet.get("totalWalletBalance") or "0"
                    new_balance = float(balance_str)
                except Exception:
                    continue

                if new_balance <= 0:
                    continue

                # Check for AI PAUSE_TRADING rule before deleting rules
                paused = False
                if self._close_svc:
                    try:
                        active_rules = await self._close_svc.list_rules(account_id)
                        for rule in active_rules:
                            if rule.get("trigger_type") == "PAUSE_TRADING" and rule.get("status") == "active":
                                ref_str = rule.get("reference_value", "")
                                hours = float(rule.get("threshold_value", 0))
                                try:
                                    ref_time = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
                                    if (datetime.now(timezone.utc) - ref_time).total_seconds() < hours * 3600:
                                        paused = True
                                        break
                                    else:
                                        await self._close_svc.delete_rule(account_id, rule["id"])
                                except (ValueError, TypeError):
                                    paused = True
                                    logger.warning("pause_rule_unparseable_fail_closed", extra={"account_id": account_id})
                                    break
                    except Exception:
                        pass
                if paused:
                    async with self._lock:
                        for state in states:
                            state.stopped = True
                            state.stopped_reason = "ai_paused_trading"
                    continue

                # Delete old rules and create fresh ones
                if self._close_svc:
                    try:
                        await self._close_svc.delete_all_rules(account_id)
                    except Exception:
                        pass

                # Reset state and re-create rules under lock
                async with self._lock:
                    for state in states:
                        state.stopped = False
                        state.stopped_reason = None
                        state.trades_executed = 0
                        state.trades_failed = 0
                        state.trades_skipped = 0
                        state.base_capital = new_balance
                        state.existing_symbols = set()
                        state.position_directions = {}
                        state.executions = []
                        state.close_rule_id = None
                        state.drawdown_rule_id = None
                        state.created_rule_ids = []
                self._emit_life(account_id, "post_scan_recheck", "state_reset", new_balance=new_balance)

                # Re-create rules (only once per account, using first state with each config)
                rules_created = False
                for state in states:
                    if rules_created:
                        break
                    if self._close_svc:
                        # Profit target rule
                        if state.config.get("target_goal_type") == "profit_pct":
                            goal_value = state.config.get("target_goal_value")
                            if goal_value and goal_value > 0:
                                try:
                                    rule = await self._close_svc.create_rule(
                                        account_id=account_id,
                                        rule_data={
                                            "trigger_type": "EQUITY_RISE_PCT",
                                            "threshold_value": str(goal_value),
                                            "reference_value": str(new_balance),
                                        },
                                    )
                                    async with self._lock:
                                        for s in states:
                                            s.close_rule_id = rule.get("id")
                                            s.created_rule_ids.append(rule.get("id"))
                                except Exception:
                                    pass
                        # Max drawdown rule
                        max_drawdown = state.config.get("max_drawdown_pct", 100)
                        if max_drawdown < 100:
                            try:
                                _dd_type = "EQUITY_DROP_PCT_SMART" if state.config.get("smart_drawdown_close") else "EQUITY_DROP_PCT"
                                rule = await self._close_svc.create_rule(
                                    account_id=account_id,
                                    rule_data={
                                        "trigger_type": _dd_type,
                                        "threshold_value": str(max_drawdown),
                                        "reference_value": str(new_balance),
                                    },
                                )
                                async with self._lock:
                                    for s in states:
                                        s.drawdown_rule_id = rule.get("id")
                                        s.created_rule_ids.append(rule.get("id"))
                            except Exception:
                                pass
                        # Breakeven timeout rule
                        breakeven_hours = state.config.get("breakeven_timeout_hours")
                        if breakeven_hours and breakeven_hours > 0:
                            from datetime import datetime, timezone as tz
                            try:
                                rule = await self._close_svc.create_rule(
                                    account_id=account_id,
                                    rule_data={
                                        "trigger_type": "BREAKEVEN_TIMEOUT",
                                        "threshold_value": str(breakeven_hours),
                                        "reference_value": datetime.now(tz.utc).isoformat(),
                                    },
                                )
                                async with self._lock:
                                    for s in states:
                                        s.created_rule_ids.append(rule.get("id"))
                            except Exception:
                                pass
                        # Max trade duration rule
                        max_duration_hours = state.config.get("max_trade_duration_hours")
                        if max_duration_hours and max_duration_hours > 0:
                            from datetime import datetime, timezone as tz
                            try:
                                rule = await self._close_svc.create_rule(
                                    account_id=account_id,
                                    rule_data={
                                        "trigger_type": "MAX_DURATION",
                                        "threshold_value": str(max_duration_hours),
                                        "reference_value": datetime.now(tz.utc).isoformat(),
                                    },
                                )
                                async with self._lock:
                                    for s in states:
                                        s.created_rule_ids.append(rule.get("id"))
                            except Exception:
                                pass
                        # Trailing profit rule
                        trailing_pct = state.config.get("trailing_profit_pct")
                        if trailing_pct and trailing_pct > 0:
                            try:
                                rule = await self._close_svc.create_rule(
                                    account_id=account_id,
                                    rule_data={
                                        "trigger_type": "TRAILING_PROFIT",
                                        "threshold_value": str(trailing_pct),
                                        "reference_value": "0",
                                    },
                                )
                                async with self._lock:
                                    for s in states:
                                        s.created_rule_ids.append(rule.get("id"))
                            except Exception:
                                pass
                        rules_created = True

                # Execute trades from scan results
                traded: set = set()
                async with self._lock:
                    for state in states:
                        if state.stopped:
                            continue
                        for result in unique_results:
                            if state.stopped:
                                break
                            ticker = result.get("ticker", "")
                            symbol = _to_symbol(ticker)
                            trade_key = (account_id, symbol)
                            if trade_key in traded:
                                continue
                            execution = await self._try_trade(state, result, phase="post_scan_recheck")
                            if execution and execution.status == "success":
                                traded.add(trade_key)
                            if execution:
                                executions.append(execution)

                # Clean up if 0 trades were successfully executed
                total_executed = sum(state.trades_executed for state in states)
                if total_executed > 0:
                    async with self._lock:
                        for state in states:
                            state.rescued_by_recheck = True
                if total_executed == 0 and self._close_svc:
                    to_delete = set()
                    async with self._lock:
                        for s in states:
                            for rid in s.created_rule_ids:
                                to_delete.add(rid)
                    for rule_id in to_delete:
                        try:
                            await self._close_svc.delete_rule(account_id, rule_id)
                        except Exception:
                            pass

            except Exception as e:
                logger.warning("post_scan_recheck_failed", extra={
                    "account_id": account_id, "error": str(e)[:200],
                })

        return executions

    async def _try_trade(self, state: "_AccountState", result: Dict[str, Any], *, relaxed: bool = False, phase: str = "batch") -> Optional[TradeExecution]:
        cfg = state.config
        account_id = cfg.get("account_id", "")
        if result.get("status") != "completed":
            return None
        direction = result.get("direction", "hold")
        confidence = result.get("confidence", "none")
        score = abs(result.get("score", 0))
        ticker = result.get("ticker", "")
        if not ticker:
            return None
        symbol = f"{ticker}USDT" if not ticker.endswith("USDT") else ticker

        blacklist = cfg.get("symbol_blacklist") or []
        if blacklist and symbol in blacklist:
            self._emit_decision(account_id, phase, symbol, "skipped", "blacklist", result)
            state.trades_skipped += 1
            return None
        whitelist = cfg.get("symbol_whitelist") or []
        if whitelist and symbol not in whitelist:
            self._emit_decision(account_id, phase, symbol, "skipped", "whitelist", result)
            state.trades_skipped += 1
            return None

        if symbol in state.existing_symbols:
            self._emit_decision(account_id, phase, symbol, "skipped", "already_held", result)
            state.trades_skipped += 1
            return None

        max_age = cfg.get("max_signal_age_minutes")
        if max_age and not relaxed and result.get("completed_at"):
            try:
                completed = datetime.fromisoformat(result["completed_at"].replace("Z", "+00:00"))
                age_minutes = (datetime.now(timezone.utc) - completed).total_seconds() / 60
                if age_minutes > max_age:
                    self._emit_decision(account_id, phase, symbol, "skipped", "max_signal_age", result, age=age_minutes, max=max_age)
                    state.trades_skipped += 1
                    return None
            except (ValueError, TypeError):
                pass

        if direction == "hold":
            self._emit_decision(account_id, phase, symbol, "skipped", "hold_signal", result)
            return None

        max_same_dir = cfg.get("max_same_direction")
        if max_same_dir:
            is_reverse = cfg.get("direction") == "reverse"
            signal_dir = "short" if direction in ("short", "sell") else "long"
            actual_dir = ("long" if signal_dir == "short" else "short") if is_reverse else signal_dir
            same_dir_count = sum(1 for d in state.position_directions.values() if d == actual_dir)
            if same_dir_count >= max_same_dir:
                self._emit_decision(account_id, phase, symbol, "skipped", "max_same_direction", result)
                state.trades_skipped += 1
                return None

        # Sector concentration limit
        max_same_sector = cfg.get("max_same_sector")
        if max_same_sector:
            _get_sec = self._sector_service.get_sector if self._sector_service else _static_get_sector
            sector = _get_sec(symbol)
            if sector != "other":
                same_sector_count = sum(1 for s in state.existing_symbols if _get_sec(s) == sector)
                if same_sector_count >= max_same_sector:
                    self._emit_decision(account_id, phase, symbol, "skipped", "max_same_sector", result, sector=sector)
                    state.trades_skipped += 1
                    return None

        # Adaptive blacklist check (pre-computed by scanner_service)
        adaptive_bl = cfg.get("_computed_adaptive_blacklist")
        if adaptive_bl:
            bl_set = adaptive_bl if isinstance(adaptive_bl, set) else set(adaptive_bl)
            if symbol in bl_set:
                self._emit_decision(account_id, phase, symbol, "skipped", "adaptive_blacklist", result)
                state.trades_skipped += 1
                return None

        # Apply filters (skipped in relaxed/fill mode)
        signal_sides = cfg.get("signal_sides", "both")
        if signal_sides != "both":
            _norm = {"long": "buy", "short": "sell", "Long": "buy", "Short": "sell"}
            normalized_side = _norm.get(signal_sides, signal_sides)
            normalized_dir = _norm.get(direction, direction)
            if normalized_side != normalized_dir:
                self._emit_decision(account_id, phase, symbol, "skipped", "signal_sides", result)
                return None

        if not relaxed:
            min_score = cfg.get("min_score", 0)
            if score < min_score:
                self._emit_decision(account_id, phase, symbol, "skipped", "min_score", result, score=score, min_score=min_score)
                state.trades_skipped += 1
                return None

            conf_filter = cfg.get("confidence_filter", "any")
            if conf_filter != "any":
                conf_order = {"high": 3, "moderate": 2, "low": 1, "none": 0}
                if conf_order.get(confidence, 0) < conf_order.get(conf_filter, 0):
                    self._emit_decision(account_id, phase, symbol, "skipped", "confidence_filter", result)
                    state.trades_skipped += 1
                    return None

        # Check limits
        if state.trades_executed >= cfg.get("max_trades", 999):
            self._emit_decision(account_id, phase, symbol, "skipped", "max_trades", result)
            state.stopped = True
            state.stopped_reason = "max_trades_reached"
            return None

        # Check target goal
        goal_type = cfg.get("target_goal_type")
        goal_value = cfg.get("target_goal_value")
        if goal_type and goal_value:
            if goal_type == "trade_count" and state.trades_executed >= goal_value:
                self._emit_decision(account_id, phase, symbol, "skipped", "target_goal_reached", result)
                state.stopped = True
                state.stopped_reason = "target_goal_reached"
                return None

        account_id = cfg["account_id"]

        if state.base_capital is None or state.base_capital <= 0:
            self._emit_decision(account_id, phase, symbol, "skipped", "no_balance", result)
            state.stopped = True
            state.stopped_reason = "no_balance_captured"
            return None

        # Price drift validation — skip if price already moved too far in signal direction
        max_drift = cfg.get("max_price_drift_pct")
        analysis_price = result.get("analysis_price")
        if max_drift and analysis_price:
            try:
                current_price = await self._accounts.get_mark_price(account_id, symbol)
                drift_pct = ((current_price - analysis_price) / analysis_price) * 100
                # Buy signal: skip if price already went UP (move consumed)
                # Sell signal: skip if price already went DOWN (move consumed)
                if direction in ("buy", "long") and drift_pct > max_drift:
                    self._emit_decision(account_id, phase, symbol, "skipped", "price_drift", result, drift=drift_pct)
                    state.trades_skipped += 1
                    return None
                if direction in ("sell", "short") and drift_pct < -max_drift:
                    self._emit_decision(account_id, phase, symbol, "skipped", "price_drift", result, drift=drift_pct)
                    state.trades_skipped += 1
                    return None
            except Exception:
                pass  # fail-open: proceed with trade if price check fails

        # Execute trade
        try:
            result_data = await asyncio.wait_for(
                self._accounts.place_trade(
                    account_id=account_id,
                    symbol=symbol,
                    signal_direction=direction,
                    trade_direction=cfg.get("direction", "straight"),
                    leverage=cfg.get("leverage", 20),
                    take_profit_pct=cfg.get("take_profit_pct", 150),
                    stop_loss_pct=cfg.get("stop_loss_pct", 100),
                    capital_pct=cfg.get("capital_pct", 5),
                    base_capital=state.base_capital,
                    source="scanner",
                    scan_result_id=result.get("id"),
                ),
                timeout=30.0,
            )
            execution = TradeExecution(
                account_id=account_id,
                symbol=symbol,
                side=result_data.get("side", direction),
                status="success",
                order_id=result_data.get("trade_id"),
                details=result_data,
            )
            state.trades_executed += 1
            state.executions.append(execution)
            state.existing_symbols.add(symbol)
            if self._recorder is not None and self._debug_ctx is not None:
                try:
                    self._recorder.emit_symbol_decision(
                        self._debug_ctx, account_id=account_id, phase=phase, symbol=symbol,
                        decision="placed", reason_code="placed_ok", reason_detail={},
                        scan_score=result.get("score"), scan_confidence=result.get("confidence"),
                        scan_direction=result.get("direction"), order_id=execution.order_id,
                    )
                except Exception:
                    pass
            _is_rev = cfg.get("direction") == "reverse"
            _sig_dir = "short" if direction in ("short", "sell") else "long"
            state.position_directions[symbol] = ("long" if _sig_dir == "short" else "short") if _is_rev else _sig_dir
            logger.info("auto_trade_executed", extra={
                "account_id": account_id, "symbol": symbol,
                "side": execution.side, "order_id": execution.order_id,
            })

            # Enable AI Manager for this account if configured
            if cfg.get("ai_manager_enabled") and account_id not in self._ai_manager_enabled_accounts:
                self._ai_manager_enabled_accounts.add(account_id)
                if self._ai_manager_service:
                    try:
                        # Preserve any existing config — only use defaults if no config exists yet
                        existing_config = None
                        try:
                            existing_dict = await self._ai_manager_service.get_config(account_id)
                            existing_config = _AIMConfig(**existing_dict)
                        except Exception:
                            pass
                        config_to_use = existing_config or _AIMConfig()
                        config_to_use.auto_enabled = True
                        await self._ai_manager_service.enable(account_id, config_to_use)
                        logger.info("ai_manager_auto_enabled", extra={"account_id": account_id})
                    except Exception as e:
                        logger.warning("ai_manager_auto_enable_failed", extra={
                            "account_id": account_id, "error": str(e)[:200],
                        })

            return execution

        except asyncio.TimeoutError:
            # Order may have been submitted to exchange before timeout.
            # Add to existing_symbols AND position_directions to prevent duplicate/excess trades.
            state.existing_symbols.add(symbol)
            _is_rev = cfg.get("direction") == "reverse"
            _sig_dir = "short" if direction in ("short", "sell") else "long"
            state.position_directions[symbol] = ("long" if _sig_dir == "short" else "short") if _is_rev else _sig_dir
            execution = TradeExecution(
                account_id=account_id,
                symbol=symbol,
                side=direction,
                status="failed",
                error="place_trade timeout (30s) — position may exist on exchange",
            )
            state.trades_failed += 1
            state.executions.append(execution)
            logger.error("auto_trade_timeout_phantom_risk", extra={
                "account_id": account_id, "symbol": symbol,
                "msg": "Trade may have opened on exchange without rules. Check positions.",
            })
            self._emit_decision(account_id, phase, symbol, "failed", "timeout", result)
            return execution

        except Exception as e:
            execution = TradeExecution(
                account_id=account_id,
                symbol=symbol,
                side=direction,
                status="failed",
                error=str(e)[:512],
            )
            state.trades_failed += 1
            state.executions.append(execution)
            logger.warning("auto_trade_failed", extra={
                "account_id": account_id, "symbol": symbol, "error": str(e)[:512],
            })

            self._emit_decision(account_id, phase, symbol, "failed", "place_error", result, error=str(e)[:200])
            return execution


@dataclass
class _AccountState:
    config: Dict[str, Any]
    trades_executed: int = 0
    trades_failed: int = 0
    trades_skipped: int = 0
    base_capital: Optional[float] = None
    stopped: bool = False
    stopped_reason: Optional[str] = None
    rescued_by_recheck: bool = False
    close_rule_id: Optional[str] = None
    drawdown_rule_id: Optional[str] = None
    executions: List[TradeExecution] = field(default_factory=list)
    existing_symbols: set = field(default_factory=set)
    position_directions: Dict[str, str] = field(default_factory=dict)
    created_rule_ids: List[str] = field(default_factory=list)
