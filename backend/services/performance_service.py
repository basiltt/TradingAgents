"""Performance analytics computed purely from the trades table (spec §3/§4.1).

Historical outputs (curve, drawdown, KPIs) read only `trades`/`trading_cycles`;
they never depend on snapshot tables or a live exchange call. Live-overlay
metrics (total_equity/unrealized_pnl/open_count) are sourced separately and
degrade to None. All money summed in Decimal, coerced to float at the boundary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from backend.services import portfolio_stats


def _npl(t: dict) -> Decimal:
    """COALESCE(net_pnl, 0) as Decimal."""
    v = t.get("net_pnl")
    return Decimal(str(v)) if v is not None else Decimal(0)


@dataclass
class TradeClassification:
    win_count: int
    loss_count: int


def classify_trades(trades: list[dict]) -> TradeClassification:
    """win = net_pnl>0, loss = net_pnl<0, breakeven/null = neither (spec §4.1)."""
    wins = sum(1 for t in trades if t.get("net_pnl") is not None and t["net_pnl"] > 0)
    losses = sum(1 for t in trades if t.get("net_pnl") is not None and t["net_pnl"] < 0)
    return TradeClassification(win_count=wins, loss_count=losses)


def compute_pnl_kpis(trades: list[dict]) -> dict[str, Any]:
    """Trade-derived KPIs over the canonical set (all numbers JSON-safe floats)."""
    total = len(trades)
    cls = classify_trades(trades)
    net = sum((_npl(t) for t in trades), Decimal(0))
    gross_realized = sum(
        (Decimal(str(t["realized_pnl"])) for t in trades if t.get("realized_pnl") is not None),
        Decimal(0),
    )
    winners = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None and t["net_pnl"] > 0]
    losers = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None and t["net_pnl"] < 0]
    gross_win = sum((Decimal(str(w)) for w in winners), Decimal(0))
    gross_loss = sum((Decimal(str(l)) for l in losers), Decimal(0))  # negative
    avg_win = float(gross_win / cls.win_count) if cls.win_count else None
    avg_loss = float(gross_loss / cls.loss_count) if cls.loss_count else None
    profit_factor = float(gross_win / abs(gross_loss)) if gross_loss != 0 else None
    expectancy = float(net / total) if total else None
    awl = (avg_win / abs(avg_loss)) if (avg_win is not None and avg_loss not in (None, 0)) else None
    pnls = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None]
    return {
        "net_pnl": float(net),
        "realized_pnl_gross": float(gross_realized),
        "win_rate": round(cls.win_count / total * 100, 4) if total else None,
        "win_count": cls.win_count,
        "loss_count": cls.loss_count,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_win_loss_ratio": awl,
        "best_trade": float(max(pnls)) if pnls else None,
        "worst_trade": float(min(pnls)) if pnls else None,
        "total_trades": total,
    }
