"""Backtest Simulation Engine — pure, synchronous, all data pre-loaded.

This module contains the core simulation loop that replays historical signals
through the full auto-trade cycle. It is designed to run in a ThreadPoolExecutor
and has ZERO I/O — all data (signals, klines, config) is injected.

The only external dependency is an optional `threading.Event` for cancellation
and an optional progress callback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend.schemas.backtest_schemas import SimulationResult

logger = logging.getLogger(__name__)


class BacktestCancelled(Exception):
    """Raised when a backtest is cancelled via cancel_event."""
    pass


@dataclass
class Position:
    """A single open simulated position."""

    symbol: str
    side: str  # "Buy" or "Sell"
    entry_price: float
    qty: float
    leverage: int
    entry_time: datetime
    tp_price: float
    sl_price: float
    liq_price: float
    entry_fee: float
    locked_margin: float
    scan_id: str = ""
    signal_score: int = 0
    signal_confidence: str = ""
    # Trailing profit state
    trailing_active: bool = False
    trailing_peak: float = 0.0
    # MFE/MAE tracking
    max_favorable_price: float = 0.0
    max_adverse_price: float = 0.0


@dataclass
class SimulationState:
    """Internal mutable state of the simulation engine."""

    wallet_balance: float = 0.0
    sizing_capital: float = 0.0  # refreshed per scan (matches production init_balances)
    open_positions: list[Position] = field(default_factory=list)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    # Cycle state
    cycle_active: bool = False
    cycle_start_equity: float = 0.0
    cycle_start_time: Optional[datetime] = None
    # Tracking
    signals_processed: int = 0
    signals_filtered: int = 0
    signals_entered: int = 0


class BacktestEngine:
    """Pure simulation engine for backtesting.

    All data is pre-loaded. Engine is synchronous (designed for ThreadPoolExecutor).
    cancel_event (threading.Event) checked every 100 candles for cooperative cancellation.
    """

    def run(
        self,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> SimulationResult:
        """Execute the backtest simulation.

        Args:
            config: Full backtest configuration (all AutoTradeConfig fields + backtest-specific).
            signals: Chronological list of scan result signals (from _load_signals).
            klines: Dict mapping symbol → list of kline dicts (ascending by open_time).
            cancel_event: If set, engine raises BacktestCancelled at next check point.
            on_progress: Called with percentage (0-100) at regular intervals.

        Returns:
            SimulationResult with trades, equity_curve, metrics, warnings, filter_stats.

        Raises:
            BacktestCancelled: If cancel_event is set during execution.
        """
        # Initialize state
        starting_capital = config["starting_capital"]
        state = SimulationState(
            wallet_balance=starting_capital,
            sizing_capital=starting_capital,
        )

        warnings: list[str] = []

        # Handle empty signals
        if not signals:
            warnings.append("no_signals_found")
            if on_progress:
                on_progress(100)
            return SimulationResult(
                trades=[],
                equity_curve=[{"ts": None, "equity": starting_capital, "drawdown_pct": 0.0}],
                metrics={},
                warnings=warnings,
                filter_stats={"signals_total": 0, "signals_filtered": 0, "signals_entered": 0},
            )

        # Check cancellation before starting
        if cancel_event and cancel_event.is_set():
            raise BacktestCancelled("Cancelled before simulation start")

        # TODO: Phase 3 Tasks 3.2-3.10 will implement the full simulation loop here
        # For now (Task 3.1 skeleton), return empty result with starting capital

        # Record initial equity point
        state.equity_curve.append({
            "ts": signals[0]["signal_time"] if signals else None,
            "equity": starting_capital,
            "drawdown_pct": 0.0,
        })

        if on_progress:
            on_progress(100)

        return SimulationResult(
            trades=state.closed_trades,
            equity_curve=state.equity_curve,
            metrics={},
            warnings=warnings,
            filter_stats={
                "signals_total": len(signals),
                "signals_filtered": state.signals_filtered,
                "signals_entered": state.signals_entered,
            },
        )
