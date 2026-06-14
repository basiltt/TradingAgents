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


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp string (with Z or offset) to an aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _max_drawdown_over(dd_series: list[dict], D: float | None) -> dict:
    """Recompute the max drawdown over a (sliced) drawdown series.

    Used so window/prev-window metrics reflect only the in-window slice. Honors the
    pct-vs-abs distinction: with D present, takes the min drawdown_pct; without D, the
    min drawdown_abs.
    """
    if not dd_series:
        return {"max_drawdown_pct": (0.0 if D is not None else None),
                "max_drawdown_abs": (None if D is not None else 0.0)}
    if D is not None:
        worst = min((p.get("drawdown_pct", 0.0) for p in dd_series), default=0.0)
        return {"max_drawdown_pct": float(worst), "max_drawdown_abs": None}
    worst = min((p.get("drawdown_abs", 0.0) for p in dd_series), default=0.0)
    return {"max_drawdown_pct": None, "max_drawdown_abs": float(worst)}


class PerformanceService:
    """Computes performance analytics from trades; live overlay is best-effort."""

    def __init__(self, db, accounts_service=None):
        self._db = db
        self._accounts = accounts_service

    async def _resolve_scope(self, scope: str) -> tuple[list[str], str | None, str | None]:
        """scope token -> (account_ids, account_type, account_id)."""
        if scope == "all":
            return await self._db.get_scope_account_ids(), None, None
        if scope in ("live", "demo"):
            return await self._db.get_scope_account_ids(account_type=scope), scope, None
        # else: a single account id
        ids = await self._db.get_scope_account_ids(account_id=scope)
        return ids, None, scope

    async def _live_overlay(self, account_ids: list[str]) -> tuple[dict, bool]:
        """Best-effort live totals via accounts_service.get_dashboard. Degrades to None.

        NOTE: dashboard cards key the account PK as ``id`` (from ``**acc``), unrealized P&L
        as ``total_perp_upl``, and these money fields are STRINGS (e.g. "123.45") or None on
        a disabled/errored card -- so coerce with float(x or 0). Verified against
        accounts_service._fetch_card.
        """
        nulls = {"total_equity": None, "unrealized_pnl": None, "open_count": None}
        if self._accounts is None or not account_ids:
            return nulls, True
        try:
            cards = await self._accounts.get_dashboard()
            wanted = set(account_ids)
            mine = [c for c in cards if c.get("id") in wanted]
            if not mine or any(c.get("total_equity") is None for c in mine):
                return nulls, True
            eq = sum(float(c.get("total_equity") or 0) for c in mine)
            upl = sum(float(c.get("total_perp_upl") or 0) for c in mine)
            oc = sum(int(c.get("positions_count") or 0) for c in mine)
            return {"total_equity": eq, "unrealized_pnl": upl, "open_count": oc}, False
        except Exception:  # noqa: BLE001 -- any live failure degrades the overlay only
            return nulls, True

    async def _fetch_scoped(self, account_ids, account_id, account_type, *, start, end):
        """Fetch the canonical trade set honoring the empty-scope sentinel.

        A single-account scope that resolved to no eligible account (account_id set but
        account_ids == []) returns [] -- it must NOT fall through to all-accounts. For
        all/live/demo, account_ids is the resolved list (or empty list = no accounts).
        """
        if account_id is not None and not account_ids:
            return []  # explicit empty scope
        if account_id is None and account_type is None and not account_ids:
            return []  # 'all' resolved to zero eligible accounts
        return await self._db.get_performance_trades(
            account_ids=account_ids or None, account_type=account_type, start=start, end=end,
        )

    async def compute_overview(self, *, scope: str, timeframe: str, anchor: datetime) -> dict:
        account_ids, account_type, account_id = await self._resolve_scope(scope)
        if account_id is not None and not account_ids:
            account_ids = []  # explicit empty -- see _fetch_scoped below
        start, end = resolve_timeframe_window(timeframe, anchor)
        cycle_eq = await self._db.get_account_first_cycle_equity(account_ids) if account_ids else {}
        first_cap = await self._db.get_account_first_trade_capital(account_ids) if account_ids else {}
        D, d_accounts = compute_starting_equity(account_ids=account_ids, cycle_equity=cycle_eq,
                                                first_trade_capital=first_cap)
        all_trades = await self._fetch_scoped(account_ids, account_id, account_type, start=None, end=None)
        win_trades = [t for t in all_trades
                      if (start is None or t["closed_at"] >= start) and t["closed_at"] < end]
        all_d = [t for t in all_trades if t["account_id"] in d_accounts]
        win_d = [t for t in win_trades if t["account_id"] in d_accounts]
        pnl = compute_pnl_kpis(win_trades)
        mc_w, mc_l = compute_max_consecutive(win_trades)
        full_curve = compute_cumulative_curve(all_trades)
        curve = [p for p in full_curve
                 if (start is None or _parse_ts(p["t"]) >= start) and _parse_ts(p["t"]) < end]
        full_dd, _ = compute_drawdown_series(all_d, D)
        dd_series = [p for p in full_dd
                     if (start is None or _parse_ts(p["t"]) >= start) and _parse_ts(p["t"]) < end]
        dd_max = _max_drawdown_over(dd_series, D)
        dd_days, dd_recovered = compute_drawdown_duration(win_d, D)
        ratios = compute_risk_ratios(all_d, D, dd_max.get("max_drawdown_pct"),
                                     window=(start, end))
        total_return_pct = (float(sum((_npl(t) for t in win_d), Decimal(0)) / Decimal(str(D)) * 100)
                            if (D and D > 0) else None)
        hold = [(t["closed_at"] - t["opened_at"]).total_seconds() / 3600
                for t in win_trades if t.get("opened_at")]
        overlay, degraded = await self._live_overlay(account_ids)
        kpis = {
            **pnl,
            "total_return_pct": total_return_pct,
            "max_consecutive_wins": mc_w, "max_consecutive_losses": mc_l,
            "avg_hold_time_hours": (sum(hold) / len(hold)) if hold else None,
            **dd_max, "drawdown_duration_days": dd_days, "drawdown_recovered": dd_recovered,
            **ratios, **overlay,
        }
        return {
            "kpis": kpis,
            "kpis_prev": await self._compute_prev(scope, timeframe, anchor, account_ids,
                                                  account_id, account_type, D, d_accounts),
            "equity_curve": curve,
            "equity_now": ({"t": anchor.isoformat(), "equity": overlay["total_equity"]}
                           if overlay["total_equity"] is not None else None),
            "drawdown_series": dd_series,
            "daily_pnl": compute_daily_pnl(win_trades),
            "monthly_pnl": compute_monthly_pnl(win_trades, D, pct_trades=win_d),
            "meta": {
                "currency": "USDT", "grouping_tz": "UTC",
                "trading_days": _trading_day_count(win_trades),
                "starting_equity": D, "return_basis": "recorded_history",
                "live_equity_available": overlay["total_equity"] is not None,
                "live_sourced": ["total_equity", "unrealized_pnl", "open_count"],
                "degraded": degraded,
            },
        }

    async def compute_trades_page(self, *, scope: str, timeframe: str, anchor: datetime,
                                  sort: str = "net_pnl", direction: str = "desc",
                                  cursor: tuple | None = None, limit: int = 50) -> dict:
        """Keyset-paginated raw trade rows for the Trades tab. Empty scope -> no rows."""
        account_ids, account_type, account_id = await self._resolve_scope(scope)
        if account_id is not None and not account_ids:
            return {"rows": [], "cursor": None, "has_more": False}
        if account_id is None and account_type is None and not account_ids:
            return {"rows": [], "cursor": None, "has_more": False}
        start, end = resolve_timeframe_window(timeframe, anchor)
        rows, next_cursor, has_more = await self._db.get_performance_trades_page(
            account_ids=account_ids or None, account_type=account_type,
            start=start, end=end, sort=sort, direction=direction, cursor=cursor, limit=limit,
        )
        shaped = []
        for r in rows:
            bc = r.get("base_capital")
            npl = r.get("net_pnl")
            net_pnl_pct = (float(npl) / float(bc) * 100) if (npl is not None and bc) else None
            hold = None
            if r.get("opened_at") and r.get("closed_at"):
                hold = (r["closed_at"] - r["opened_at"]).total_seconds() / 3600
            shaped.append({
                "id": r["id"], "symbol": r["symbol"], "side": r["side"],
                "net_pnl": float(npl) if npl is not None else None,
                "net_pnl_pct": net_pnl_pct,
                "close_reason": r.get("close_reason"),
                "opened_at": r["opened_at"].isoformat() if r.get("opened_at") else None,
                "closed_at": r["closed_at"].isoformat() if r.get("closed_at") else None,
                "hold_hours": hold,
            })
        return {"rows": shaped, "cursor": next_cursor, "has_more": has_more}

    async def compute_breakdowns_for(self, *, scope: str, timeframe: str, anchor: datetime) -> dict:
        """Resolve scope+window then compute bounded breakdown aggregates (Phase 3)."""
        account_ids, account_type, account_id = await self._resolve_scope(scope)
        start, end = resolve_timeframe_window(timeframe, anchor)
        trades = await self._fetch_scoped(account_ids, account_id, account_type, start=start, end=end)
        return compute_breakdowns(trades)

    async def _compute_prev(self, scope, timeframe, anchor, account_ids, account_id,
                            account_type, D, d_accounts) -> dict | None:
        """Prior equal-length window KPIs for hero delta chips. None for ALL.

        ``d_accounts`` is the set of accounts that contributed to D -- %/ratio metrics use
        only their trades (same aggregate null-D rule as compute_overview).
        """
        if timeframe == "ALL":
            return None
        start, _ = resolve_timeframe_window(timeframe, anchor)
        if start is None:
            return None
        prev_len = anchor - start
        prev_start, prev_end = start - prev_len, start  # equal-length window before start
        all_prev = await self._fetch_scoped(account_ids, account_id, account_type, start=None, end=prev_end)
        all_prev = [t for t in all_prev if t["closed_at"] < prev_end]
        prev_win = [t for t in all_prev if t["closed_at"] >= prev_start]
        all_prev_d = [t for t in all_prev if t["account_id"] in d_accounts]
        pnl = compute_pnl_kpis(prev_win)  # dollar/win KPIs over all in-scope
        cum_to_prev_end = float(sum((_npl(t) for t in all_prev_d), Decimal(0)))
        full_dd, _ = compute_drawdown_series(all_prev_d, D)
        prev_dd = [p for p in full_dd if p["t"] and prev_start <= _parse_ts(p["t"]) < prev_end]
        dd_max = _max_drawdown_over(prev_dd, D)
        ratios = compute_risk_ratios(all_prev_d, D, dd_max.get("max_drawdown_pct"),
                                     window=(prev_start, prev_end))
        return {
            "total_equity": (D + cum_to_prev_end) if D is not None else None,
            "net_pnl": pnl["net_pnl"], "win_rate": pnl["win_rate"],
            "sharpe_ratio": ratios["sharpe_ratio"],
            "max_drawdown_pct": dd_max.get("max_drawdown_pct"),
            "total_trades": pnl["total_trades"],
        }


# ── Trades-breakdown (Phase 3) ───────────────────────────────────────────────


def _win_rate(trades: list[dict]) -> float | None:
    n = len(trades)
    if not n:
        return None
    wins = sum(1 for t in trades if t.get("net_pnl") is not None and t["net_pnl"] > 0)
    return round(wins / n * 100, 4)


def _group_sum(trades: list[dict]) -> tuple[int, float, float | None]:
    """(count, sum net_pnl, win_rate) for a group."""
    total = float(sum((_npl(t) for t in trades), Decimal(0)))
    return len(trades), total, _win_rate(trades)


def compute_breakdowns(trades: list[dict]) -> dict:
    """Per-symbol / per-strategy / close-reason / P&L-distribution / hold-time breakdowns.

    Bounded GROUP BY aggregates (no pagination). Win definition net_pnl > 0.
    `meta.strategy_legacy_approximate` is True when any 'trend' trade is present, because
    migration 44 force-defaulted every pre-existing row's strategy_kind to 'trend' (so a
    'trend' label may be a backfill, not a real classification) -- the split is approximate.
    """
    # by symbol
    by_symbol_map: dict[str, list[dict]] = {}
    by_strategy_map: dict[str, list[dict]] = {}
    by_reason_map: dict[str, list[dict]] = {}
    for t in trades:
        by_symbol_map.setdefault(t["symbol"], []).append(t)
        by_strategy_map.setdefault(t.get("strategy_kind") or "trend", []).append(t)
        by_reason_map.setdefault(t.get("close_reason") or "unknown", []).append(t)

    def _rows(m, key):
        out = []
        for name, grp in m.items():
            cnt, pnl, wr = _group_sum(grp)
            out.append({key: name, "trades": cnt, "count": cnt, "pnl": pnl, "win_rate": wr})
        return sorted(out, key=lambda r: r["pnl"], reverse=True)

    by_symbol = _rows(by_symbol_map, "symbol")
    by_strategy = _rows(by_strategy_map, "strategy")
    by_close_reason = [
        {"reason": name, "count": len(grp), "pnl": float(sum((_npl(t) for t in grp), Decimal(0)))}
        for name, grp in sorted(by_reason_map.items())
    ]

    # P&L distribution by realized_pnl_pct bucket
    dist_buckets = [
        ("<-5%", lambda v: v < -5),
        ("-5 to 0%", lambda v: -5 <= v < 0),
        ("0 to 2%", lambda v: 0 <= v < 2),
        ("2 to 5%", lambda v: 2 <= v < 5),
        (">5%", lambda v: v >= 5),
    ]
    dist_counts = {label: 0 for label, _ in dist_buckets}
    for t in trades:
        v = t.get("realized_pnl_pct")
        if v is None:
            continue
        for label, pred in dist_buckets:
            if pred(float(v)):
                dist_counts[label] += 1
                break
    pnl_distribution = [{"bucket": label, "count": dist_counts[label]} for label, _ in dist_buckets]

    # hold-time buckets (hours between opened_at and closed_at)
    hold_buckets = [
        ("<1h", lambda h: h < 1),
        ("1-4h", lambda h: 1 <= h < 4),
        ("4-24h", lambda h: 4 <= h < 24),
        (">24h", lambda h: h >= 24),
    ]
    hold_groups: dict[str, list[dict]] = {label: [] for label, _ in hold_buckets}
    for t in trades:
        if not t.get("opened_at") or not t.get("closed_at"):
            continue
        h = (t["closed_at"] - t["opened_at"]).total_seconds() / 3600
        for label, pred in hold_buckets:
            if pred(h):
                hold_groups[label].append(t)
                break
    hold_time_buckets = [
        {"bucket": label, "count": len(hold_groups[label]), "win_rate": _win_rate(hold_groups[label])}
        for label, _ in hold_buckets
    ]

    legacy = any((t.get("strategy_kind") or "trend") == "trend" for t in trades)

    return {
        "by_symbol": by_symbol,
        "by_strategy": by_strategy,
        "by_close_reason": by_close_reason,
        "pnl_distribution": pnl_distribution,
        "hold_time_buckets": hold_time_buckets,
        "meta": {"strategy_legacy_approximate": legacy},
    }
