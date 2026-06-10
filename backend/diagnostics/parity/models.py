"""Dataclasses for the backtest-parity diagnostic harness."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LiveTrade:
    """One closed live trade — the ground-truth oracle row."""
    symbol: str
    side: str                 # "Buy"/"Sell" as stored in trades.side
    net_pnl: float
    close_reason: str
    entry_price: float
    exit_price: float | None
    scan_result_id: int | None
    opened_at: datetime
    closed_at: datetime | None

    @property
    def pin_key(self) -> tuple[str, str]:
        """(symbol, lowercase side) — the key used to pin engine selection."""
        return (self.symbol, self.side.lower())

    @property
    def is_external(self) -> bool:
        return self.close_reason == "external"


@dataclass
class Cycle:
    """One trading cycle = one scan's executed trades for the account."""
    scan_id: str
    signal_time: datetime
    base_capital: float
    live_trades: list[LiveTrade] = field(default_factory=list)

    @property
    def pinned_set(self) -> set[tuple[str, str]]:
        return {t.pin_key for t in self.live_trades}

    @property
    def live_net_pnl(self) -> float:
        return sum(t.net_pnl for t in self.live_trades)


@dataclass
class CycleComparison:
    """Per-cycle live vs backtest result."""
    scan_id: str
    signal_time: datetime
    live_net_pnl: float
    backtest_net_pnl: float
    live_equity_after: float
    backtest_equity_after: float

    @property
    def delta_pct(self) -> float:
        if self.live_equity_after == 0:
            return 0.0
        return (self.backtest_equity_after - self.live_equity_after) / self.live_equity_after * 100.0


@dataclass
class ParityReport:
    """Final report: per-cycle table + headline final-equity delta."""
    live_final_equity: float
    backtest_final_equity: float
    cycles: list[CycleComparison]
    tolerance_pct: float = 1.0

    @property
    def final_equity_delta_pct(self) -> float:
        if self.live_final_equity == 0:
            return 0.0
        return (self.backtest_final_equity - self.live_final_equity) / self.live_final_equity * 100.0

    @property
    def passed(self) -> bool:
        return abs(self.final_equity_delta_pct) <= self.tolerance_pct
