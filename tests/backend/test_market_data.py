"""Tests for market_data classifier + EMA mean (Phase 1 TASK-1.1/1.2)."""

from backend.services.market_data import (
    classify_regime,
    compute_atr_ratio,
    compute_ema_mean,
    compute_ema_distance_pct,
    ema,
    required_depth,
)


def _kline(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 1.0, "open_time": 0}


def _flat_series(n, price=100.0):
    # zero true range, flat closes -> ranging
    return [_kline(price, price, price, price) for _ in range(n)]


def _trending_series(n, start=100.0, step=2.0):
    # steadily rising closes far above EMA -> trending
    out = []
    p = start
    for _ in range(n):
        out.append(_kline(p, p + 0.1, p - 0.1, p))
        p += step
    return out


def _volatile_series(n):
    # last bars have a huge true range vs the average -> high atr_ratio
    out = [_kline(100, 100.5, 99.5, 100) for _ in range(n - 2)]
    out.append(_kline(100, 130, 70, 100))   # massive range spike
    out.append(_kline(100, 135, 65, 100))
    return out


# ── EMA primitives ──

def test_ema_known_value():
    # EMA period 3 over [1,2,3,4,5]; seed=mean(1,2,3)=2, k=0.5
    # e=2; v=4 -> 4*.5+2*.5=3; v=5 -> 5*.5+3*.5=4
    assert ema([1, 2, 3, 4, 5], 3) == 4.0


def test_ema_insufficient_returns_none():
    assert ema([1, 2], 3) is None


def test_compute_ema_mean_insufficient():
    assert compute_ema_mean(_flat_series(5), 20) is None


def test_compute_ema_mean_value():
    assert compute_ema_mean(_flat_series(30, price=100.0), 20) == 100.0


# ── atr_ratio depth guard (SD1a) ──

def test_atr_ratio_none_when_below_required_depth():
    # required_depth(14) = 29; 28 candles -> None (not a degenerate 1.0)
    assert compute_atr_ratio(_volatile_series(28), 14) is None
    assert required_depth(14) == 29


def test_atr_ratio_not_degenerate_one_at_min_depth():
    # at exactly required depth on a volatile series, ratio must be computable and != ~1.0
    ratio = compute_atr_ratio(_volatile_series(29), 14)
    assert ratio is not None
    assert ratio > 1.2  # the spike pushes the latest ATR well above its SMA


# ── classify_regime truth table (T-22) ──

def test_classify_unknown_insufficient_candles():
    r = classify_regime(_flat_series(10), lookback=14)
    assert r["regime"] == "unknown"
    assert r["unavailable"] is True


def test_classify_ranging_flat_market():
    r = classify_regime(_flat_series(40), lookback=14)
    assert r["regime"] == "ranging"
    assert r["unavailable"] is False


def test_classify_trending_market():
    r = classify_regime(_trending_series(40), lookback=14)
    assert r["regime"] == "trending"


def test_classify_volatile_market():
    r = classify_regime(_volatile_series(40), lookback=14, volatile_atr=2.0)
    assert r["regime"] == "volatile"


def test_classify_boundary_volatile_threshold():
    # if atr_ratio is exactly the threshold -> volatile (>=)
    series = _volatile_series(40)
    ratio = compute_atr_ratio(series, 14)
    r = classify_regime(series, lookback=14, volatile_atr=ratio)
    assert r["regime"] == "volatile"


def test_ema_distance_pct_sign():
    # rising market: last close above EMA -> positive distance
    d = compute_ema_distance_pct(_trending_series(40), 14)
    assert d is not None and d > 0
