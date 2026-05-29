"""Tests for regime_classifier pure functions."""

from __future__ import annotations

import math
import random

import pytest

from backend.services.regime_classifier import classify_from_indicators, compute_indicators


# ---------------------------------------------------------------------------
# classify_from_indicators tests
# ---------------------------------------------------------------------------


def test_trending_up():
    regime = classify_from_indicators(
        adx=30,
        price=100,
        ema20=95,
        atr_pct=0.5,
        atr_avg_30=0.5,
        bb_width=3.0,
        bb_width_median=3.0,
    )
    assert regime == "trending_up"


def test_trending_down():
    regime = classify_from_indicators(
        adx=30,
        price=90,
        ema20=95,
        atr_pct=0.5,
        atr_avg_30=0.5,
        bb_width=3.0,
        bb_width_median=3.0,
    )
    assert regime == "trending_down"


def test_volatile():
    # atr_pct=2.0 > 1.5 * 0.8 = 1.2
    regime = classify_from_indicators(
        adx=15,
        price=100,
        ema20=100,
        atr_pct=2.0,
        atr_avg_30=0.8,
        bb_width=3.0,
        bb_width_median=3.0,
    )
    assert regime == "volatile"


def test_ranging():
    regime = classify_from_indicators(
        adx=15,
        price=100,
        ema20=100,
        atr_pct=0.5,
        atr_avg_30=0.5,
        bb_width=2.0,
        bb_width_median=3.5,
    )
    assert regime == "ranging"


def test_volatile_priority_over_trending():
    """Volatile wins even when ADX > 25 and price > ema20."""
    regime = classify_from_indicators(
        adx=30,
        price=100,
        ema20=95,
        atr_pct=2.0,   # 2.0 > 1.5 * 0.8 = 1.2
        atr_avg_30=0.8,
        bb_width=3.0,
        bb_width_median=3.0,
    )
    assert regime == "volatile"


# ---------------------------------------------------------------------------
# compute_indicators tests
# ---------------------------------------------------------------------------


def _make_candles(n: int = 50, seed: int = 42) -> list[dict]:
    """Generate synthetic OHLC candles with a mild uptrend."""
    rng = random.Random(seed)
    candles = []
    price = 100.0
    for _ in range(n):
        change = rng.uniform(-1.5, 2.0)
        open_ = price
        close = max(1.0, price + change)
        high = max(open_, close) + rng.uniform(0, 1.0)
        low = min(open_, close) - rng.uniform(0, 1.0)
        candles.append({"open": open_, "high": high, "low": low, "close": close})
        price = close
    return candles


def test_compute_indicators_returns_all_keys():
    candles = _make_candles(50)
    result = compute_indicators(candles)
    expected_keys = {"adx", "atr_pct", "atr_avg_30", "ema20", "price", "bb_width", "bb_width_median"}
    assert expected_keys == set(result.keys())


def test_compute_indicators_values_are_finite():
    candles = _make_candles(50)
    result = compute_indicators(candles)
    for key, value in result.items():
        assert math.isfinite(value), f"{key} = {value} is not finite"


def test_compute_indicators_requires_30_candles():
    with pytest.raises(ValueError, match="30"):
        compute_indicators(_make_candles(20))


def test_compute_indicators_price_matches_last_close():
    candles = _make_candles(50)
    result = compute_indicators(candles)
    assert result["price"] == pytest.approx(candles[-1]["close"])
