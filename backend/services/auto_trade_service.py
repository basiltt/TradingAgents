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

    def __init__(self, accounts_service: Any):
        self._accounts = accounts_service
        self._state: Dict[str, _AccountState] = {}
        self._lock = asyncio.Lock()

    def init_configs(self, configs: List[Dict[str, Any]]) -> None:
        self._state.clear()
        for i, cfg in enumerate(configs):
            key = f"{cfg['account_id']}_{i}"
            self._state[key] = _AccountState(config=cfg)

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
                "executions": [
                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                     "order_id": e.order_id, "error": e.error}
                    for e in state.executions
                ],
            })
        return summaries

    async def _try_trade(self, state: "_AccountState", result: Dict[str, Any]) -> Optional[TradeExecution]:
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

        if direction == "hold":
            return None

        # Apply filters
        signal_sides = cfg.get("signal_sides", "both")
        if signal_sides != "both" and signal_sides != direction:
            return None

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

        # Fetch base capital if not cached
        if state.base_capital is None:
            try:
                wallet = await self._accounts.get_wallet(cfg["account_id"])
                balance_str = wallet.get("totalAvailableBalance") or wallet.get("totalWalletBalance") or "0"
                state.base_capital = float(balance_str)
            except Exception as e:
                logger.warning("auto_trade_wallet_fetch_failed", extra={"account_id": cfg["account_id"], "error": str(e)[:512]})
                state.stopped = True
                state.stopped_reason = f"wallet_fetch_failed: {str(e)[:200]}"
                return None

        if state.base_capital <= 0:
            state.stopped = True
            state.stopped_reason = "zero_balance"
            return None

        # Execute trade
        try:
            result_data = await self._accounts.place_trade(
                account_id=cfg["account_id"],
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
                account_id=cfg["account_id"],
                symbol=symbol,
                side=result_data.get("side", direction),
                status="success",
                order_id=result_data.get("trade_id"),
                details=result_data,
            )
            state.trades_executed += 1
            state.executions.append(execution)
            logger.info("auto_trade_executed", extra={
                "account_id": cfg["account_id"], "symbol": symbol,
                "side": execution.side, "order_id": execution.order_id,
            })
            return execution

        except Exception as e:
            execution = TradeExecution(
                account_id=cfg["account_id"],
                symbol=symbol,
                side=direction,
                status="failed",
                error=str(e)[:512],
            )
            state.trades_failed += 1
            state.executions.append(execution)
            logger.warning("auto_trade_failed", extra={
                "account_id": cfg["account_id"], "symbol": symbol, "error": str(e)[:512],
            })

            # Check max drawdown (simplified — count failures)
            max_drawdown = cfg.get("max_drawdown_pct", 100)
            if state.trades_failed > 3 and max_drawdown < 100:
                state.stopped = True
                state.stopped_reason = "max_drawdown_protection"

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
    executions: List[TradeExecution] = field(default_factory=list)
