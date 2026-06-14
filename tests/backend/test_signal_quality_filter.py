"""Tests for signal_quality_filter (FIX-005 trade-selection filters)."""
from __future__ import annotations

from backend.services.signal_quality_filter import (
    trend_direction, trend_aligned, is_falling_knife_short,
)


def _kl(closes, highs=None, lows=None):
    """Build ASC klines from close list; highs/lows default to close +/- tiny."""
    out = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.001
        l = lows[i] if lows else c * 0.999
        out.append({"o": c, "h": h, "l": l, "c": c, "v": 100.0})
    return out


# ── trend_direction ──────────────────────────────────────────────────────────
def test_trend_direction_up():
    kl = _kl([float(i) for i in range(1, 40)])  # steadily rising
    assert trend_direction(kl) == "up"

def test_trend_direction_down():
    kl = _kl([float(i) for i in range(40, 1, -1)])  # steadily falling
    assert trend_direction(kl) == "down"

def test_trend_direction_insufficient():
    assert trend_direction(_kl([1.0, 2.0, 3.0])) is None  # < slow period


# ── trend_aligned ────────────────────────────────────────────────────────────
def test_short_aligned_with_downtrend():
    down = _kl([float(i) for i in range(40, 1, -1)])
    assert trend_aligned("sell", down, down) is True

def test_short_against_uptrend_is_not_aligned():
    up = _kl([float(i) for i in range(1, 40)])
    assert trend_aligned("sell", up, up) is False

def test_long_aligned_with_uptrend():
    up = _kl([float(i) for i in range(1, 40)])
    assert trend_aligned("buy", up, up) is True

def test_mixed_timeframes_not_aligned():
    up = _kl([float(i) for i in range(1, 40)])
    down = _kl([float(i) for i in range(40, 1, -1)])
    # short wants down on BOTH; 1h up, 4h down -> not aligned
    assert trend_aligned("sell", up, down) is False

def test_trend_aligned_failopen_on_insufficient():
    short_kl = _kl([1.0, 2.0, 3.0])
    # None == fail-open: caller should ALLOW the trade
    assert trend_aligned("sell", short_kl, short_kl) is None


# ── is_falling_knife_short ───────────────────────────────────────────────────
def test_falling_knife_crashed_and_oversold():
    # 60 candles, crashed ~30% over the window, ending oversold near the low
    closes = [100.0] * 10 + [100 - i for i in range(0, 70)]  # long steady drop to ~30
    kl = _kl(closes)
    assert is_falling_knife_short("sell", kl) is True

def test_not_falling_knife_when_not_crashed():
    closes = [100.0 + (i % 3) for i in range(60)]  # flat/choppy, no crash
    kl = _kl(closes)
    assert is_falling_knife_short("sell", kl) is False

def test_falling_knife_only_applies_to_shorts():
    closes = [100.0] * 10 + [100 - i for i in range(0, 70)]
    kl = _kl(closes)
    assert is_falling_knife_short("buy", kl) is False  # longs never knife-blocked

def test_falling_knife_failopen_on_short_history():
    assert is_falling_knife_short("sell", _kl([100.0, 99.0, 98.0])) is False
