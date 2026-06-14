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


def compute_starting_equity(
    *, account_ids: list[str], cycle_equity: dict[str, float],
    first_trade_capital: dict[str, float],
) -> tuple[float | None, set[str]]:
    """D = sum per-account starting equity (cycle initial_equity, else first base_capital).

    ONE value per account; accounts with neither are EXCLUDED (spec §3). Returns
    (D, contributing_account_ids). D is None when no account contributes a positive
    value. The contributing set lets callers exclude a null-D account's P&L from the
    numerator of every %/ratio metric (spec §4.1 aggregate null-D rule) so its profit is
    never divided by other accounts' capital.
    """
    total = Decimal(0)
    contributing: set[str] = set()
    for aid in account_ids:
        val = cycle_equity.get(aid)
        if val is None:
            val = first_trade_capital.get(aid)
        if val is not None and val > 0:
            total += Decimal(str(val))
            contributing.add(aid)
    if not contributing or total <= 0:
        return None, set()
    return float(total), contributing


def compute_cumulative_curve(trades: list[dict]) -> list[dict]:
    """Cumulative net P&L from origin 0, per trade, with running peak (spec §4.1)."""
    out: list[dict] = []
    cum = Decimal(0)
    peak = Decimal(0)
    for t in trades:
        cum += _npl(t)
        peak = max(peak, cum)
        out.append({
            "t": t["closed_at"].isoformat() if hasattr(t["closed_at"], "isoformat") else t["closed_at"],
            "cum_pnl": float(cum),
            "peak": float(peak),
        })
    return out


def compute_drawdown_series(
    trades: list[dict], D: float | None,
) -> tuple[list[dict], dict]:
    """Drawdown from running peak of equity_proxy = D + cum_pnl, peak SEEDED AT D.

    Returns (series, max_drawdown). When D is present, series carries drawdown_pct
    and the second return is {"max_drawdown_pct": ..., "max_drawdown_abs": None}.
    When D is None, series carries drawdown_abs and the second return mirrors it.
    The peak is seeded at the pre-first-trade equity (D, or 0 when D is None) so an
    initial losing streak registers real drawdown (spec §4.1 -- do NOT seed at proxy[0]).
    """
    base = Decimal(str(D)) if D is not None else Decimal(0)
    cum = Decimal(0)
    peak = base  # SEED AT D (not equity_proxy[0])
    series: list[dict] = []
    worst_pct = Decimal(0)
    worst_abs = Decimal(0)
    for t in trades:
        cum += _npl(t)
        proxy = base + cum
        peak = max(peak, proxy)
        ts = t["closed_at"].isoformat() if hasattr(t["closed_at"], "isoformat") else t["closed_at"]
        if D is not None and peak > 0:
            dd = (proxy - peak) / peak * Decimal(100)
            worst_pct = min(worst_pct, dd)
            series.append({"t": ts, "drawdown_pct": float(dd)})
        else:
            dd_abs = proxy - peak
            worst_abs = min(worst_abs, dd_abs)
            series.append({"t": ts, "drawdown_abs": float(dd_abs)})
    if D is not None:
        return series, {"max_drawdown_pct": float(worst_pct), "max_drawdown_abs": None}
    return series, {"max_drawdown_pct": None, "max_drawdown_abs": float(worst_abs)}
