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


_MIN_TRADING_DAYS = 10


def compute_max_consecutive(trades: list[dict]) -> tuple[int, int]:
    """Longest win / loss streak over the PER-TRADE sequence (NOT the daily series).

    Trades are already ordered closed_at,id. Reuses portfolio_stats.max_consecutive
    by mapping each trade to +1 (win) / -1 (loss) / 0 (breakeven/null breaks streak).
    """
    seq = []
    for t in trades:
        v = t.get("net_pnl")
        seq.append(1.0 if (v is not None and v > 0) else (-1.0 if (v is not None and v < 0) else 0.0))
    wins = portfolio_stats.max_consecutive(seq, negative=False)
    losses = portfolio_stats.max_consecutive(seq, negative=True)
    return wins, losses


def _trading_day_count(trades: list[dict]) -> int:
    return len({t["closed_at"].date() for t in trades if t.get("closed_at") is not None})


def build_daily_return_series(trades: list[dict], D: float) -> list[tuple[Any, float]]:
    """Forward-filled UTC-calendar-day % return series for Sharpe/Sortino/Calmar.

    Built over ALL of `trades` (origin 0). Day set = every UTC calendar day from first to
    last trading day, inclusive. No-trade days carry equity forward -> 0% return. First day
    seeded at D. Returns (date, return_pct) pairs so a caller can restrict to a window
    WITHOUT re-seeding the window's first day (spec §4.1 step 5).
    """
    if not trades or D is None or D <= 0:
        return []
    by_day: dict[Any, Decimal] = {}
    cum = Decimal(0)
    for t in trades:
        cum += _npl(t)
        by_day[t["closed_at"].date()] = cum  # last write per day = end-of-day cum
    days = sorted(by_day.keys())
    first, last = days[0], days[-1]
    base = Decimal(str(D))
    out: list[tuple[Any, float]] = []
    prev_proxy = base  # before first day
    cur_cum = Decimal(0)
    d = first
    one = timedelta(days=1)
    while d <= last:
        if d in by_day:
            cur_cum = by_day[d]
        proxy = base + cur_cum
        ret = float((proxy - prev_proxy) / prev_proxy * Decimal(100)) if prev_proxy > 0 else 0.0
        out.append((d, ret))
        prev_proxy = proxy
        d = d + one
    return out


def compute_risk_ratios(
    trades: list[dict], D: float | None, max_drawdown_pct: float | None,
    window: "tuple[datetime | None, datetime] | None" = None,
) -> dict[str, float | None]:
    """Sharpe/Sortino/Calmar from the daily-% series; None below 10 trading days,
    on D-null, or on degenerate (zero variance / zero drawdown). Calmar uses abs(dd).

    `trades` is the ALL-HISTORY set; the all-history daily-% series is built once and then
    restricted to days within `window` (spec §4.1 step 5 -- first in-window day keeps its
    recurrence return, NOT a re-seed at D). When window is None, the whole series is used.
    The <10 gate counts distinct TRADING days within the window.
    """
    nulls = {"sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None}
    if D is None or D <= 0:
        return dict(nulls)
    pairs = build_daily_return_series(trades, D)  # [(date, return_pct), ...] all-history
    if window is not None:
        start, end = window
        sd = start.date() if start is not None else None
        ed = end.date()
        pairs = [(d, r) for (d, r) in pairs if (sd is None or d >= sd) and d < ed]
    series = [r for (_d, r) in pairs]
    win_trades = trades
    if window is not None:
        start, end = window
        win_trades = [t for t in trades
                      if (start is None or t["closed_at"] >= start) and t["closed_at"] < end]
    if _trading_day_count(win_trades) < _MIN_TRADING_DAYS:
        return dict(nulls)
    if len(series) < 2:
        return dict(nulls)
    # zero-variance guard (helpers would return 0.0 -> we want None)
    mean = sum(series) / len(series)
    if all(abs(r - mean) < 1e-12 for r in series):
        sharpe = sortino = None
    else:
        sharpe = portfolio_stats.calc_sharpe(series) or None  # 0.0 -> None
        sortino = portfolio_stats.calc_sortino(series) or None
    # Calmar: None on no-drawdown; also map a 0.0 result (zero mean return) -> None for parity.
    calmar = None if max_drawdown_pct in (None, 0) else (portfolio_stats.calc_calmar(series, abs(max_drawdown_pct)) or None)
    return {"sharpe_ratio": sharpe, "sortino_ratio": sortino, "calmar_ratio": calmar}


_TF = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}


def resolve_timeframe_window(timeframe: str, anchor: datetime) -> tuple[datetime | None, datetime]:
    """Resolve a timeframe token to [start, anchor) in UTC (spec §4.2). ALL -> start None."""
    if timeframe not in _TF:
        raise ValueError(f"unknown timeframe: {timeframe}")
    if timeframe == "ALL":
        return None, anchor
    if timeframe == "1D":
        return anchor - timedelta(hours=24), anchor
    if timeframe == "1W":
        return anchor - timedelta(days=7), anchor
    if timeframe == "1M":
        return anchor - relativedelta(months=1), anchor
    if timeframe == "3M":
        return anchor - relativedelta(months=3), anchor
    if timeframe == "1Y":
        return anchor - relativedelta(years=1), anchor
    if timeframe == "YTD":
        return datetime(anchor.year, 1, 1, tzinfo=timezone.utc), anchor
    raise ValueError(timeframe)  # unreachable


def compute_daily_pnl(trades: list[dict]) -> list[dict]:
    """Sum net_pnl by UTC close date, oldest first."""
    agg: dict[Any, Decimal] = {}
    for t in trades:
        d = t["closed_at"].date()
        agg[d] = agg.get(d, Decimal(0)) + _npl(t)
    return [{"date": d.isoformat(), "pnl": float(v)} for d, v in sorted(agg.items())]


def compute_monthly_pnl(trades: list[dict], D: float | None,
                        pct_trades: "list[dict] | None" = None) -> list[dict]:
    """Monthly grid. Dollar `pnl` sums `net_pnl` over `trades` (every in-scope account).
    `return_pct = month_pnl / D` is computed from `pct_trades` -- the D-relative subset
    (accounts that contributed to D) so a null-D account's P&L is never divided by other
    accounts' capital (spec §4.1). Defaults `pct_trades = trades` when not given.
    """
    pct_trades = trades if pct_trades is None else pct_trades
    agg: dict[str, Decimal] = {}
    for t in trades:
        key = t["closed_at"].strftime("%Y-%m")
        agg[key] = agg.get(key, Decimal(0)) + _npl(t)
    pct_agg: dict[str, Decimal] = {}
    for t in pct_trades:
        key = t["closed_at"].strftime("%Y-%m")
        pct_agg[key] = pct_agg.get(key, Decimal(0)) + _npl(t)
    out = []
    for key, v in sorted(agg.items()):
        rp = (float(pct_agg.get(key, Decimal(0)) / Decimal(str(D)) * 100)
              if (D and D > 0) else None)
        out.append({"month": key, "pnl": float(v), "return_pct": rp})
    return out


def compute_drawdown_duration(trades: list[dict], D: float | None) -> tuple[int | None, bool]:
    """Duration (floored days) of the single deepest drawdown episode, + recovered flag.

    Walk equity_proxy = D + cum (peak seeded at D). Track the running peak's timestamp;
    find the trough with the largest drop from its preceding peak; duration = peak->
    (recovery that reclaims peak, else last trade), floored. Returns (None, True) when
    there is no drawdown or D is None.
    """
    if not trades or D is None:
        return None, True
    base = Decimal(str(D))
    cum = Decimal(0)
    peak = base
    peak_ts = trades[0]["closed_at"]  # pre-first-trade peak time ~ first close
    worst_drop = Decimal(0)
    worst_peak_ts = None
    worst_trough_idx = -1
    for i, t in enumerate(trades):
        cum += _npl(t)
        proxy = base + cum
        if proxy >= peak:
            peak = proxy
            peak_ts = t["closed_at"]
        else:
            drop = peak - proxy
            if drop > worst_drop:
                worst_drop = drop
                worst_peak_ts = peak_ts
                worst_trough_idx = i
    if worst_trough_idx < 0 or worst_peak_ts is None:
        return 0, True
    # find recovery: first later trade whose proxy reclaims the worst episode's peak
    base_peak = None
    cum2 = Decimal(0)
    pk = base
    for i, t in enumerate(trades):
        cum2 += _npl(t)
        proxy = base + cum2
        pk = max(pk, proxy)
        if i == worst_trough_idx:
            base_peak = pk
    recovery_ts = None
    cum3 = Decimal(0)
    for i, t in enumerate(trades):
        cum3 += _npl(t)
        if i > worst_trough_idx and (base + cum3) >= base_peak:
            recovery_ts = t["closed_at"]
            break
    if recovery_ts is not None:
        return int((recovery_ts - worst_peak_ts).total_seconds() // 86400), True
    last_ts = trades[-1]["closed_at"]
    return int((last_ts - worst_peak_ts).total_seconds() // 86400), False
