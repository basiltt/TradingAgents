"""Backtest Metrics — TradingView-parity metric computation.

Pure functions computing all standard backtest metrics from a trade list
and equity curve. No I/O, fully deterministic.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

# Annualization factor for crypto (trades 365 days/year, no market close)
ANNUALIZATION_DAYS = 365
# Hard cap on CAGR % to keep the value finite/JSON-safe under extreme short-span growth
CAGR_CAP_PCT = 1.0e9


def _finite(value: Any) -> Optional[float]:
    """Return value as a finite float, or None if it is None/NaN/Infinity/non-numeric.

    Accepts int, float, and Decimal (asyncpg returns NUMERIC columns as Decimal,
    so DB-sourced pnl/fees/equity/capital arrive as Decimal and MUST be accepted —
    rejecting them would silently zero valid values). bool is rejected as
    non-numeric. NaN/Infinity (in any of those types) map to None.

    The conversion to float is itself validated: an enormous Decimal/int whose
    own .is_finite()/isfinite() is True can still produce an inf float (or raise
    OverflowError) — both are caught and mapped to None so the result is ALWAYS
    a finite float or None.
    """
    if isinstance(value, bool):  # bool is an int subclass — treat as non-numeric here
        return None
    if not isinstance(value, (int, float, Decimal)):
        return None
    try:
        f = float(value)
    except (ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _hours_between(start: Any, end: Any) -> Optional[float]:
    """Hours between two datetimes, or None if either is not a usable datetime.

    Tolerates naive/aware mismatch (a common data-source hazard) by falling
    back to a naive comparison rather than raising TypeError.
    """
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    try:
        return (end - start).total_seconds() / 3600.0
    except TypeError:
        # naive vs aware mismatch — strip tzinfo and compare as naive
        try:
            s = start.replace(tzinfo=None)
            e = end.replace(tzinfo=None)
            return (e - s).total_seconds() / 3600.0
        except (TypeError, ValueError):
            return None


def _json_safe(obj: Any) -> Any:
    """Recursively coerce a structure into strict-JSON-safe values.

    json.dumps defaults to allow_nan=True and emits the invalid JSON literals
    `Infinity`/`NaN`, which break PostgreSQL JSONB inserts and browser
    JSON.parse. It also cannot serialize Decimal, datetime, or set natively.
    This pass guarantees every leaf is a finite float / int / str / bool / None:
      - non-finite float (inf/-inf/nan) -> None
      - Decimal -> finite float, or None if NaN/Infinity/overflows float
      - datetime -> ISO 8601 string
      - set/frozenset/tuple -> list
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Decimal):
        return _finite(obj)  # total: huge-but-finite Decimal -> None (not inf)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        # Sets have non-deterministic iteration order (and depend on
        # PYTHONHASHSEED for strings) — sort by JSON repr so the serialized
        # output is reproducible run-to-run. (Defensive: no metric value is a
        # set today, but this bulletproofs reproducibility if one is ever added.)
        items = [_json_safe(v) for v in obj]
        try:
            items.sort(key=lambda x: json.dumps(x, sort_keys=True))
        except TypeError:
            items.sort(key=repr)
        return items
    if obj is None or isinstance(obj, (str, int)):
        return obj
    # Unknown leaf type (bytes, UUID, numpy scalar, custom object, ...) — coerce
    # to str so the result is ALWAYS strict-JSON-serializable, by construction.
    return str(obj)


def compute_sharpe(daily_returns: list[float], risk_free: float = 0.0) -> Optional[float]:
    """Compute Sharpe ratio, annualized for crypto (√365).

    Args:
        daily_returns: List of period returns (as decimals).
        risk_free: Risk-free rate (default 0).

    Returns:
        Annualized Sharpe ratio, or None if <2 data points or zero std.
    """
    if len(daily_returns) < 2:
        return None
    mean_return = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return ((mean_return - risk_free) / std) * math.sqrt(ANNUALIZATION_DAYS)


def compute_sortino(daily_returns: list[float], risk_free: float = 0.0) -> Optional[float]:
    """Compute Sortino ratio (downside deviation only), annualized √365.

    Args:
        daily_returns: List of period returns.
        risk_free: Risk-free rate.

    Returns:
        Annualized Sortino ratio, or None if <2 data points OR there are no
        downside periods (downside deviation is then undefined — like an
        infinite ratio — so we return None for the UI to show "∞"/"N/A",
        consistent with how profit_factor handles a no-loss strategy).
    """
    if len(daily_returns) < 2:
        return None
    mean_return = sum(daily_returns) / len(daily_returns)
    downside = [r for r in daily_returns if r < risk_free]
    if not downside:
        return None  # no losing periods — Sortino undefined (not a giant fake number)
    downside_var = sum((r - risk_free) ** 2 for r in downside) / len(daily_returns)
    downside_dev = math.sqrt(downside_var)
    if downside_dev == 0:
        # Defensive: downside non-empty implies var>0, so this is effectively
        # unreachable, but guard div-by-zero from float underflow regardless.
        return None
    return ((mean_return - risk_free) / downside_dev) * math.sqrt(ANNUALIZATION_DAYS)


def compute_max_drawdown(equity_curve: list[dict[str, Any]]) -> dict[str, float]:
    """Compute maximum drawdown from equity curve.

    Tracks the max drawdown by PERCENTAGE and by DOLLARS independently — on a
    growing equity curve the deepest % and deepest $ drawdowns occur at
    different points, and recovery_factor depends on the true max-$ value.

    INVARIANT: equity_curve MUST be in chronological order — the running
    peak/trough tracking assumes each point follows the previous in time. The
    engine builds the curve append-only in simulation-time order, satisfying
    this. Unsorted input would produce an incorrect drawdown.

    Non-finite or non-numeric equity points are skipped defensively so a bad
    simulator value can never crash the comparison or leak NaN.

    Args:
        equity_curve: List of {ts, equity, drawdown_pct} dicts (chronological).

    Returns:
        Dict with max_dd_pct, max_dd_usd, max_dd_duration_hours, avg_dd_pct.
    """
    # Coerce to (equity_float, ts) pairs up front so ALL arithmetic is on floats.
    # (DB equity arrives as Decimal; raw Decimal math would make max_dd_usd a
    # Decimal and crash float/Decimal division in recovery_factor/calmar.)
    points = [
        (e, p.get("ts"))
        for p, e in ((p, _finite(p.get("equity"))) for p in equity_curve)
        if e is not None
    ]
    if not points:
        return {"max_dd_pct": 0.0, "max_dd_usd": 0.0, "max_dd_duration_hours": 0.0, "avg_dd_pct": 0.0}

    peak, peak_time = points[0]
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    max_dd_duration = 0.0
    drawdowns = []

    for equity, ts in points:
        if equity > peak:
            peak = equity
            peak_time = ts
        if peak > 0:
            dd_usd = peak - equity
            dd_pct = (dd_usd / peak) * 100
            drawdowns.append(dd_pct)
            # Track max $ drawdown independently of max % drawdown
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            # Track max % drawdown, and measure its peak->trough duration
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                dur = _hours_between(peak_time, ts)
                if dur is not None:
                    # Clamp to 0: the authoritative terminal equity point may carry
                    # an earlier ts than a force-close point, which could otherwise
                    # yield a spurious negative duration. Magnitude is unaffected.
                    max_dd_duration = max(0.0, dur)

    avg_dd = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0

    return {
        "max_dd_pct": max_dd_pct,
        "max_dd_usd": max_dd_usd,
        "max_dd_duration_hours": max_dd_duration,
        "avg_dd_pct": avg_dd,
    }


def compute_run_up(equity_curve: list[dict[str, Any]]) -> dict[str, float]:
    """Compute maximum run-up (the mirror of drawdown) from the equity curve.

    Run-up at a point is the rise from the lowest prior trough to that point;
    max run-up is the largest such rise (tracked in $ and %). Non-finite or
    non-numeric equity points are skipped defensively.

    INVARIANT: equity_curve MUST be in chronological order (running trough
    tracking depends on it). The engine builds it append-only in time order.

    Args:
        equity_curve: List of {ts, equity} dicts (chronological).

    Returns:
        Dict with max_run_up_pct, max_run_up_usd.
    """
    # Coerce every equity to a finite float up front (handles DB Decimal too)
    equities = [e for e in (_finite(p.get("equity")) for p in equity_curve) if e is not None]
    if not equities:
        return {"max_run_up_pct": 0.0, "max_run_up_usd": 0.0}

    trough = equities[0]
    max_ru_pct = 0.0
    max_ru_usd = 0.0

    for equity in equities:
        if equity < trough:
            trough = equity
        ru_usd = equity - trough
        if ru_usd > max_ru_usd:
            max_ru_usd = ru_usd
        if trough > 0:
            ru_pct = (ru_usd / trough) * 100
            if ru_pct > max_ru_pct:
                max_ru_pct = ru_pct

    return {"max_run_up_pct": max_ru_pct, "max_run_up_usd": max_ru_usd}


def compute_durations(trades: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    """Compute trade-duration metrics (overall / winners / losers / max), in hours.

    Trades are expected in chronological close order with exit_time >= entry_time.
    A negative duration (exit before entry) is physically impossible and signals
    corrupted/reconstructed data — such trades are skipped from the duration
    averages rather than poisoning them with a negative value.

    Args:
        trades: List of trade dicts with entry_time, exit_time, pnl.

    Returns:
        Dict with avg_trade_duration_hours, avg_winner_duration_hours,
        avg_loser_duration_hours, max_trade_duration_hours (None when N/A).
    """
    all_durs: list[float] = []
    win_durs: list[float] = []
    loss_durs: list[float] = []

    for t in trades:
        dur = _hours_between(t.get("entry_time"), t.get("exit_time"))
        if dur is None or dur < 0:  # skip missing AND impossible (negative) durations
            continue
        all_durs.append(dur)
        pnl = _finite(t.get("pnl")) or 0.0
        if pnl > 0:
            win_durs.append(dur)
        elif pnl < 0:
            loss_durs.append(dur)

    def _avg(xs: list[float]) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    return {
        "avg_trade_duration_hours": _avg(all_durs),
        "avg_winner_duration_hours": _avg(win_durs),
        "avg_loser_duration_hours": _avg(loss_durs),
        "max_trade_duration_hours": (max(all_durs) if all_durs else None),
    }


def compute_per_trade_series(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-trade detail series with running cumulative PnL (spec FR-006 Per-Trade).

    Trades are assumed already ordered by exit time (the engine appends them in
    close order). Each entry carries MFE, MAE, close reason, pnl, and the
    cumulative PnL through that trade.

    Entries are emitted ALREADY JSON-safe (numerics via _finite → finite-float-or-
    None; datetimes → ISO 8601 strings; symbol/side/close_reason → str-or-None).
    This lets compute_all_metrics skip re-walking this (potentially 50k-entry)
    list through _json_safe — avoiding ~500k redundant isinstance calls and a full
    copy of the list at scale.

    Args:
        trades: Ordered list of closed-trade dicts.

    Returns:
        List of {index, symbol, side, pnl, cumulative_pnl, mfe_pct, mae_pct,
        close_reason, entry_time, exit_time} dicts — all values JSON-serializable.
    """
    def _iso(v: Any) -> Optional[str]:
        return v.isoformat() if isinstance(v, datetime) else None

    def _label(v: Any) -> Optional[str]:
        # symbol/side/close_reason are strings from the engine; coerce defensively
        return v if (v is None or isinstance(v, str)) else str(v)

    series: list[dict[str, Any]] = []
    cumulative = 0.0
    for i, t in enumerate(trades):
        pnl = _finite(t.get("pnl")) or 0.0
        cumulative += pnl
        series.append({
            "index": i,
            "symbol": _label(t.get("symbol")),
            "side": _label(t.get("side")),
            "pnl": pnl,
            # Guard the running sum: float accumulation could overflow to inf
            # (this value bypasses the _json_safe pass for performance, so it
            # must be made JSON-safe here at the source).
            "cumulative_pnl": cumulative if math.isfinite(cumulative) else None,
            "mfe_pct": _finite(t.get("mfe_pct")),
            "mae_pct": _finite(t.get("mae_pct")),
            "close_reason": _label(t.get("close_reason")),
            "entry_time": _iso(t.get("entry_time")),
            "exit_time": _iso(t.get("exit_time")),
        })
    return series


def compute_streaks(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute consecutive win/loss streaks.

    Args:
        trades: List of trade dicts with 'pnl' field.

    Returns:
        Dict with max_consecutive_wins/losses (count) and their $ amounts.
    """
    max_wins = 0
    max_losses = 0
    cur_wins = 0
    cur_losses = 0
    max_win_usd = 0.0
    max_loss_usd = 0.0
    cur_win_usd = 0.0
    cur_loss_usd = 0.0

    for trade in trades:
        pnl = _finite(trade.get("pnl")) or 0.0
        if pnl > 0:
            cur_wins += 1
            cur_win_usd += pnl
            cur_losses = 0
            cur_loss_usd = 0.0
            if cur_wins > max_wins:
                max_wins = cur_wins
                max_win_usd = cur_win_usd
        elif pnl < 0:
            cur_losses += 1
            cur_loss_usd += pnl
            cur_wins = 0
            cur_win_usd = 0.0
            if cur_losses > max_losses:
                max_losses = cur_losses
                max_loss_usd = cur_loss_usd
        else:
            # A breakeven trade (pnl == 0) is neither a win nor a loss and BREAKS
            # both runs — otherwise W, BE, W would over-report a 2-win streak.
            cur_wins = 0
            cur_win_usd = 0.0
            cur_losses = 0
            cur_loss_usd = 0.0

    return {
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "max_consecutive_wins_usd": max_win_usd,
        "max_consecutive_losses_usd": max_loss_usd,
    }


def _direction_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the core metric subset for a trade list (used by split_by_direction)."""
    if not trades:
        return {
            "total_trades": 0, "winners": 0, "losers": 0,
            "net_profit": 0.0, "win_rate": None,
            "avg_trade": None, "avg_win": None, "avg_loss": None,
        }

    pnls = [_finite(t.get("pnl")) or 0.0 for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    net = sum(pnls)

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "net_profit": net,
        "win_rate": (len(winners) / len(trades) * 100),
        "avg_trade": net / len(trades),
        "avg_win": (sum(winners) / len(winners)) if winners else None,
        "avg_loss": (sum(losers) / len(losers)) if losers else None,
    }


def split_by_direction(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Split metrics into All / Long / Short.

    Args:
        trades: List of trade dicts with 'side' field.

    Returns:
        Dict with 'all', 'long', 'short' keys, each a metric subset.
    """
    longs = [t for t in trades if t.get("side") == "Buy"]
    shorts = [t for t in trades if t.get("side") == "Sell"]

    return {
        "all": _direction_metrics(trades),
        "long": _direction_metrics(longs),
        "short": _direction_metrics(shorts),
    }


def compute_by_strategy(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Split metrics by strategy_kind x direction (F2 validation breakdown).

    Returns {"<strategy_kind>:<long|short>": metric_subset}, e.g. "trend:short",
    "mean_reversion:long". A trade with no strategy_kind buckets under "trend"
    (legacy/trend). Reuses _direction_metrics so the shape matches by_direction; the
    frontend StrategyPnLView consumes this to compare trend vs mean-reversion. Empty
    input -> {}.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for t in trades or []:
        kind = t.get("strategy_kind") or "trend"
        direction = "long" if t.get("side") == "Buy" else "short"
        buckets.setdefault(f"{kind}:{direction}", []).append(t)
    return {key: _direction_metrics(ts) for key, ts in buckets.items()}


def _consecutive_returns(values: list[float]) -> list[float]:
    """Period-over-period returns over a sequence of equity values.

    Skips any step whose prior value is <= 0 (return undefined there).
    """
    out = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev > 0:
            out.append((values[i] - prev) / prev)
    return out


def _compute_daily_returns(equity_curve: list[dict[str, Any]]) -> list[float]:
    """Resample equity curve to daily buckets, return list of daily returns.

    The equity curve has irregular timestamps (one per scan event). To make
    √365 annualization correct, we sample the LAST equity value per calendar
    day and compute day-over-day returns.

    If the curve has no datetime timestamps (or fewer than 2 distinct days),
    falls back to point-to-point returns over consecutive equity values so
    Sharpe/Sortino still get data (slightly overstated, but better than empty).

    Args:
        equity_curve: List of {ts, equity} dicts.

    Returns:
        List of returns (decimals). Empty only if fewer than 2 equity points.
    """
    if len(equity_curve) < 2:
        return []

    # Bucket by calendar date — keep last equity per day
    daily_equity: dict[Any, float] = {}
    has_timestamps = False
    for point in equity_curve:
        ts = point.get("ts")
        equity = _finite(point.get("equity"))
        if ts is None or equity is None:
            continue
        if isinstance(ts, datetime):
            has_timestamps = True
            # Normalize to UTC before bucketing so the SAME instant always lands
            # in the same calendar day regardless of whether the source supplied
            # a naive (assumed-UTC) or tz-aware timestamp — keeps Sharpe/Sortino
            # reproducible across data sources (DB vs cache).
            day_key = (ts.astimezone(timezone.utc) if ts.tzinfo else ts).date()
            daily_equity[day_key] = equity  # last value for the day wins

    if not has_timestamps or len(daily_equity) < 2:
        # Fall back to point-to-point returns over finite equity values only
        finite_equities = [
            e for e in (_finite(p.get("equity")) for p in equity_curve) if e is not None
        ]
        return _consecutive_returns(finite_equities)

    # Sort by date and compute day-over-day returns
    sorted_days = sorted(daily_equity.keys())
    return _consecutive_returns([daily_equity[d] for d in sorted_days])


def compute_buy_hold_return(
    btc_klines: list[dict[str, Any]],
    starting_capital: float,
) -> dict[str, float]:
    """Compute Buy & Hold benchmark return for BTC/USDT.

    Args:
        btc_klines: BTC kline data (ascending by time) with 'close' field.
        starting_capital: Initial capital.

    Returns:
        Dict with return_pct, final_value, start_price, end_price.
    """
    capital = _finite(starting_capital) or 0.0
    if not btc_klines:
        return {"return_pct": 0.0, "final_value": capital, "start_price": 0.0, "end_price": 0.0}

    # Coerce prices via _finite — klines may be DB-sourced (asyncpg Decimal).
    start_price = _finite(btc_klines[0].get("close"))
    end_price = _finite(btc_klines[-1].get("close"))

    if start_price is None or end_price is None or start_price <= 0:
        return {
            "return_pct": 0.0, "final_value": capital,
            "start_price": start_price or 0.0, "end_price": end_price or 0.0,
        }

    return_pct = (end_price - start_price) / start_price * 100
    final_value = capital * (1 + return_pct / 100)

    # _json_safe guarantees JSON-safety even if the price ratio overflowed
    # (e.g. a huge end_price over a subnormal start_price → inf).
    return _json_safe({
        "return_pct": return_pct,
        "final_value": final_value,
        "start_price": start_price,
        "end_price": end_price,
    })


def _compute_cagr(
    equity_curve: list[dict[str, Any]],
    starting_capital: float,
    final_equity: float,
) -> Optional[float]:
    """Compound annual growth rate (%), or None if not computable.

    Computed in log space (expm1/log) for numerical stability and wrapped so
    extreme short-span growth can never overflow to Infinity. Result is clamped
    to [-100, CAGR_CAP_PCT] to stay JSON-safe.

    Returns None for spans under one day. Annualizing a sub-day run (e.g. a +5%
    move over 2 hours) would project it over 365/(<1) days and report a nonsensical
    multi-million-percent CAGR. CAGR is only meaningful over multi-day horizons, so
    below a day we report N/A rather than a fabricated number the UI would show as
    a real growth rate.
    """
    if len(equity_curve) < 2 or starting_capital <= 0 or final_equity <= 0:
        return None
    first_ts = equity_curve[0].get("ts")
    last_ts = equity_curve[-1].get("ts")
    hours = _hours_between(first_ts, last_ts)
    if hours is None:
        return None
    days = hours / 24.0
    if days < 1.0:
        return None  # sub-day span — annualized CAGR is not meaningful
    ratio = final_equity / starting_capital
    try:
        cagr = math.expm1((ANNUALIZATION_DAYS / days) * math.log(ratio)) * 100
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(cagr):
        return None
    return max(min(cagr, CAGR_CAP_PCT), -100.0)


def compute_all_metrics(
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Compute ALL TradingView-parity metrics.

    Args:
        trades: List of closed trade dicts.
        equity_curve: List of equity points.
        config: Backtest config (for starting_capital, etc).

    Returns:
        Complete metrics dict. Includes a `diagnostics` sub-dict reporting how
        many inputs had to be sanitized (dropped/coerced) — all-zero in the
        normal case; non-zero signals upstream (engine) data problems that the
        caller should surface via SimulationResult.warnings rather than letting
        them silently distort the metrics.
    """
    raw_trades = trades or []
    raw_equity = equity_curve or []
    # Defensively normalize inputs so malformed args can never crash aggregation:
    # drop non-dict list elements (would AttributeError on .get) and guard a None config.
    trades = [t for t in raw_trades if isinstance(t, dict)]
    equity_curve = [p for p in raw_equity if isinstance(p, dict)]
    config = config or {}

    # Single _finite pass over pnls — reused for diagnostics AND the normal-path
    # aggregation (avoids a second full pass at 50k scale).
    finite_pnls = [_finite(t.get("pnl")) for t in trades]

    # Diagnostics — count what we had to sanitize so silent coercion is observable.
    # Mirrors the trade/equity value-corruption that would otherwise silently
    # distort metrics. None (missing) is excluded — only present-but-bad counts.
    diagnostics = {
        "trades_dropped_non_dict": len(raw_trades) - len(trades),
        "equity_points_dropped_non_dict": len(raw_equity) - len(equity_curve),
        # non-finite pnl values coerced to 0.0 (would silently dilute trade metrics)
        "trade_pnls_sanitized": sum(
            1 for fp, t in zip(finite_pnls, trades, strict=True)
            if fp is None and t.get("pnl") is not None
        ),
        # non-finite equity values skipped in drawdown/run-up/Sharpe (wider blast radius)
        "equity_values_sanitized": sum(
            1 for p in equity_curve
            if _finite(p.get("equity")) is None and p.get("equity") is not None
        ),
    }

    # Sanitize starting_capital — config is user-supplied and untrusted, may be
    # a string, None, NaN, or Inf. Coerce to a finite float (0.0 if unusable).
    starting_capital = _finite(config.get("starting_capital")) or 0.0

    # Handle zero trades — must emit SAME keys as the normal path (schema parity)
    if not trades:
        final_equity = _finite(equity_curve[-1].get("equity")) if equity_curve else None
        if final_equity is None:
            final_equity = starting_capital
        ru = compute_run_up(equity_curve)
        return _json_safe({
            "total_trades": 0, "winners": 0, "losers": 0,
            "net_profit": 0.0, "net_profit_pct": (0.0 if starting_capital > 0 else None),
            "gross_profit": 0.0, "gross_loss": 0.0,
            "win_rate": None, "profit_factor": None,
            "sharpe": None, "sortino": None,
            "max_dd_pct": 0.0, "max_dd_usd": 0.0,
            "max_dd_duration_hours": 0.0, "avg_dd_pct": 0.0,
            "max_run_up_pct": ru["max_run_up_pct"], "max_run_up_usd": ru["max_run_up_usd"],
            "avg_trade": None, "avg_win": None, "avg_loss": None,
            "avg_win_loss_ratio": None,
            "largest_win": None, "largest_loss": None,
            "total_commission": 0.0, "recovery_factor": None,
            "cagr": None, "calmar": None, "expectancy": None,
            "max_consecutive_wins": 0, "max_consecutive_losses": 0,
            "max_consecutive_wins_usd": 0.0, "max_consecutive_losses_usd": 0.0,
            "avg_trade_duration_hours": None,
            "avg_winner_duration_hours": None, "avg_loser_duration_hours": None,
            "max_trade_duration_hours": None,
            "final_equity": final_equity,
            # empty list — cheap to pass through _json_safe here; the populated
            # normal path attaches per_trade AFTER the _json_safe pass for perf
            # (do not "unify" by moving that one inside — see compute_per_trade_series).
            "per_trade": [],
            "by_direction": split_by_direction([]),
            "by_strategy": compute_by_strategy([]),
            "diagnostics": diagnostics,
        })

    # Sanitize untrusted numeric trade fields (pnl, fees) so a NaN/Inf from the
    # simulator can never propagate into the output or crash comparisons.
    # pnls reuses the finite_pnls computed once above for diagnostics.
    pnls = [p or 0.0 for p in finite_pnls]
    fees = [_finite(t.get("fees_paid")) or 0.0 for t in trades]

    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    # NOTE: each trade's pnl is recorded NET of all commissions and funding (see
    # backtest_engine._close_position). So gross_profit/gross_loss here are the
    # net-of-cost winner/loser sums, and net_profit == gross_profit + gross_loss
    # already — commission is NOT to be subtracted again. total_commission is a
    # standalone memo (sum of fees+funding), never a term in the net_profit
    # identity. net_profit reconciles with final_equity - starting_capital.
    gross_profit = sum(winners)
    gross_loss = sum(losers)  # negative
    net_profit = sum(pnls)
    total_commission = sum(fees)

    # Profit factor — None when no losses (avoid Infinity which breaks JSON/JSONB)
    if gross_loss == 0:
        profit_factor = None  # "no losses" — UI shows "∞" / "N/A"
    else:
        profit_factor = gross_profit / abs(gross_loss)

    # Win rate
    win_rate = (len(winners) / len(trades)) * 100

    # Avg win/loss/trade
    avg_win = (gross_profit / len(winners)) if winners else None
    avg_loss = (gross_loss / len(losers)) if losers else None
    avg_trade = net_profit / len(trades)  # TradingView "Avg Trade"
    # Ratio of avg win to avg loss magnitude (TradingView headline row)
    if avg_win is not None and avg_loss is not None and avg_loss != 0:
        avg_win_loss_ratio = avg_win / abs(avg_loss)
    else:
        avg_win_loss_ratio = None

    # Largest
    largest_win = max(winners, default=None)
    largest_loss = min(losers, default=None)

    # Expectancy = average $ result per trade. Algebraically identical to the
    # win/loss-decomposition form (win_rate·avg_win + loss_rate·avg_loss) and to
    # avg_trade; breakeven trades correctly dilute it via the len(trades) divisor.
    expectancy = avg_trade

    # Equity-based metrics
    final_equity = _finite(equity_curve[-1].get("equity")) if equity_curve else None
    if final_equity is None:
        final_equity = starting_capital + net_profit
    net_profit_pct = (net_profit / starting_capital * 100) if starting_capital > 0 else None

    # Drawdown
    dd = compute_max_drawdown(equity_curve)

    # Recovery factor = net profit / max drawdown $
    recovery_factor = (net_profit / dd["max_dd_usd"]) if dd["max_dd_usd"] > 0 else None

    # Daily returns for Sharpe/Sortino — resample equity curve to DAILY buckets
    # so the √365 annualization is correct (curve points are irregular per-scan)
    daily_returns = _compute_daily_returns(equity_curve)

    sharpe = compute_sharpe(daily_returns)
    sortino = compute_sortino(daily_returns)

    # CAGR — log-space, overflow-guarded, capped (see _compute_cagr)
    cagr = _compute_cagr(equity_curve, starting_capital, final_equity)

    # Calmar = CAGR / max_dd_pct
    calmar = (cagr / dd["max_dd_pct"]) if (cagr is not None and dd["max_dd_pct"] > 0) else None

    # Streaks
    streaks = compute_streaks(trades)

    # Durations — overall / winner / loser / max (tz-mismatch tolerant)
    durs = compute_durations(trades)

    # Run-up (mirror of drawdown) and per-trade cumulative-PnL series.
    # per_trade is emitted ALREADY JSON-safe by compute_per_trade_series, so it
    # is attached AFTER the _json_safe pass to avoid re-walking (and copying) a
    # list that can hold 50k entries at scale.
    ru = compute_run_up(equity_curve)
    per_trade = compute_per_trade_series(trades)

    result = _json_safe({
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "net_profit": net_profit,
        "net_profit_pct": net_profit_pct,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd_pct": dd["max_dd_pct"],
        "max_dd_usd": dd["max_dd_usd"],
        "max_dd_duration_hours": dd["max_dd_duration_hours"],
        "avg_dd_pct": dd["avg_dd_pct"],
        "max_run_up_pct": ru["max_run_up_pct"],
        "max_run_up_usd": ru["max_run_up_usd"],
        "avg_trade": avg_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_win_loss_ratio": avg_win_loss_ratio,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "total_commission": total_commission,
        "recovery_factor": recovery_factor,
        "cagr": cagr,
        "calmar": calmar,
        "expectancy": expectancy,
        "max_consecutive_wins": streaks["max_consecutive_wins"],
        "max_consecutive_losses": streaks["max_consecutive_losses"],
        "max_consecutive_wins_usd": streaks["max_consecutive_wins_usd"],
        "max_consecutive_losses_usd": streaks["max_consecutive_losses_usd"],
        "avg_trade_duration_hours": durs["avg_trade_duration_hours"],
        "avg_winner_duration_hours": durs["avg_winner_duration_hours"],
        "avg_loser_duration_hours": durs["avg_loser_duration_hours"],
        "max_trade_duration_hours": durs["max_trade_duration_hours"],
        "final_equity": final_equity,
        "by_direction": split_by_direction(trades),
        "by_strategy": compute_by_strategy(trades),
        "diagnostics": diagnostics,
    })
    # Attach the pre-sanitized large list without a second pass.
    result["per_trade"] = per_trade
    return result
