"""Auto-trade execution service for market scans."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

    def __init__(self, accounts_service: Any, close_positions_service: Any = None):
        self._accounts = accounts_service
        self._close_svc = close_positions_service
        self._state: Dict[str, _AccountState] = {}
        self._lock = asyncio.Lock()

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
                wallet_balance = float(wallet.get("totalWalletBalance") or "0")
                unrealized = float(wallet.get("totalPerpUPL") or "0")
                if wallet_balance > 0 and unrealized > 0:
                    pnl_pct = (unrealized / wallet_balance) * 100
                    # Threshold = close_pct% of the target_goal equity rise
                    effective_threshold = (close_pct / 100) * target_goal
                    if pnl_pct >= effective_threshold:
                        logger.info("auto_trade_force_close_triggered", extra={
                            "account_id": account_id, "pnl_pct": round(pnl_pct, 2),
                            "effective_threshold": round(effective_threshold, 2),
                            "close_pct": close_pct, "target_goal": target_goal,
                        })
                        await self._close_svc.close_all_positions(account_id)
                        await asyncio.sleep(2)
                        force_closed_accounts.add(account_id)
            except Exception as e:
                logger.warning("auto_trade_close_on_profit_check_failed", extra={"account_id": account_id, "error": str(e)[:200]})

        for key, state in self._state.items():
            if state.stopped:
                continue
            account_id = state.config["account_id"]
            if not account_id:
                state.stopped = True
                state.stopped_reason = "no_account_id"
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
            # Create close rules (only once per account per cycle)
            if account_id not in rules_created_for:
                # Delete any leftover rules from previous scans before creating new ones
                if self._close_svc:
                    try:
                        cleared = await self._close_svc.delete_all_rules(account_id)
                        if cleared:
                            logger.info("auto_trade_cleared_stale_rules", extra={"account_id": account_id, "count": cleared})
                    except Exception:
                        logger.warning("auto_trade_clear_rules_failed", extra={"account_id": account_id})
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
                        rule = await self._close_svc.create_rule(
                            account_id=account_id,
                            rule_data={
                                "trigger_type": "EQUITY_DROP_PCT",
                                "threshold_value": str(max_drawdown),
                                "reference_value": str(state.base_capital),
                            },
                        )
                        state.drawdown_rule_id = rule.get("id")
                        logger.info("auto_trade_drawdown_rule_created", extra={"account_id": account_id, "rule_id": state.drawdown_rule_id, "threshold": max_drawdown})
                    except Exception as e:
                        state.stopped = True
                        state.stopped_reason = "drawdown_rule_creation_failed"
                        logger.warning("auto_trade_drawdown_rule_failed", extra={"account_id": account_id, "error": str(e)[:512]})
                        continue
                rules_created_for.add(account_id)

        # Propagate rule IDs and base_capital to sibling configs sharing the same account
        account_rule_map: Dict[str, tuple] = {}
        for state in self._state.values():
            aid = state.config["account_id"]
            if state.close_rule_id or state.drawdown_rule_id or state.base_capital:
                account_rule_map.setdefault(aid, (state.close_rule_id, state.drawdown_rule_id, state.base_capital))
        for state in self._state.values():
            aid = state.config["account_id"]
            if aid in account_rule_map:
                cr, dr, bc = account_rule_map[aid]
                if not state.close_rule_id and cr:
                    state.close_rule_id = cr
                if not state.drawdown_rule_id and dr:
                    state.drawdown_rule_id = dr
                if state.base_capital is None and bc:
                    state.base_capital = bc

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
                execution = await self._try_trade(state, result)
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
            unique_results = list(seen.values())

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
                    execution = await self._try_trade(state, result)
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
                    execution = await self._try_trade(state, result, relaxed=True)
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

            def _to_symbol(ticker: str) -> str:
                return ticker if ticker.endswith("USDT") else f"{ticker}USDT"

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
                    execution = await self._try_trade(state, result, relaxed=True)
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

        # Delete rules only for accounts with zero total trades
        for aid, has_trades in account_has_trades.items():
            if has_trades:
                continue
            for rule_id in account_rules.get(aid, set()):
                try:
                    await self._close_svc.delete_rule(aid, rule_id)
                except Exception:
                    pass

    async def _try_trade(self, state: "_AccountState", result: Dict[str, Any], *, relaxed: bool = False) -> Optional[TradeExecution]:
        cfg = state.config
        if result.get("status") != "completed":
            return None
        direction = result.get("direction", "hold")
        confidence = result.get("confidence", "none")
        score = abs(result.get("score", 0))
        ticker = result.get("ticker", "")
        if not ticker:
            return None
        symbol = f"{ticker}USDT" if not ticker.endswith("USDT") else ticker

        if symbol in state.existing_symbols:
            state.trades_skipped += 1
            return None

        if direction == "hold":
            return None

        # Apply filters (skipped in relaxed/fill mode)
        signal_sides = cfg.get("signal_sides", "both")
        if signal_sides != "both" and signal_sides != direction:
            return None

        if not relaxed:
            min_score = cfg.get("min_score", 0)
            if score < min_score:
                state.trades_skipped += 1
                return None

            conf_filter = cfg.get("confidence_filter", "any")
            if conf_filter != "any":
                conf_order = {"high": 3, "moderate": 2, "low": 1, "none": 0}
                if conf_order.get(confidence, 0) < conf_order.get(conf_filter, 0):
                    state.trades_skipped += 1
                    return None

        # Check limits
        if state.trades_executed >= cfg.get("max_trades", 999):
            state.stopped = True
            state.stopped_reason = "max_trades_reached"
            return None

        # Check target goal
        goal_type = cfg.get("target_goal_type")
        goal_value = cfg.get("target_goal_value")
        if goal_type and goal_value:
            if goal_type == "trade_count" and state.trades_executed >= goal_value:
                state.stopped = True
                state.stopped_reason = "target_goal_reached"
                return None

        account_id = cfg["account_id"]

        if state.base_capital is None or state.base_capital <= 0:
            state.stopped = True
            state.stopped_reason = "no_balance_captured"
            return None

        # Execute trade
        try:
            result_data = await self._accounts.place_trade(
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
            logger.info("auto_trade_executed", extra={
                "account_id": account_id, "symbol": symbol,
                "side": execution.side, "order_id": execution.order_id,
            })
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
    close_rule_id: Optional[str] = None
    drawdown_rule_id: Optional[str] = None
    executions: List[TradeExecution] = field(default_factory=list)
    existing_symbols: set = field(default_factory=set)
