"""Tests for Phase 3: Multi-timeframe analysis + new data sources."""

from __future__ import annotations

import pytest
from tradingagents.dataflows.bybit_data import (
    get_higher_timeframe,
    _parse_kline_csv,
    get_volatility_metrics,
    get_market_regime,
    estimate_liquidation_price,
    project_funding_cost,
)


class TestHigherTimeframe:
    def test_minute_intervals(self):
        assert get_higher_timeframe("1") == "60"
        assert get_higher_timeframe("3") == "60"
        assert get_higher_timeframe("5") == "60"

    def test_fifteen_min(self):
        assert get_higher_timeframe("15") == "240"

    def test_hourly(self):
        assert get_higher_timeframe("60") == "240"

    def test_four_hour(self):
        assert get_higher_timeframe("240") == "D"

    def test_daily(self):
        assert get_higher_timeframe("D") == "W"

    def test_weekly_no_higher(self):
        assert get_higher_timeframe("W") is None

    def test_unknown_interval(self):
        assert get_higher_timeframe("999") is None


class TestParseKlineCsv:
    def test_basic_parse(self):
        csv = "timestamp,open,high,low,close,volume\n1000,100,105,95,102,500"
        df = _parse_kline_csv(csv)
        assert len(df) == 1
        assert df["close"].iloc[0] == 102

    def test_skips_warning_lines(self):
        csv = "[WARNING: truncated]\ntimestamp,open,high,low,close,volume\n1000,100,105,95,102,500"
        df = _parse_kline_csv(csv)
        assert len(df) == 1


def _make_kline_csv(n: int = 250, base_price: float = 100.0) -> str:
    import random
    random.seed(42)
    lines = ["timestamp,open,high,low,close,volume"]
    price = base_price
    for i in range(n):
        change = random.uniform(-2, 2)
        o = price
        c = price + change
        h = max(o, c) + random.uniform(0, 1)
        l = min(o, c) - random.uniform(0, 1)
        v = random.uniform(100, 1000)
        lines.append(f"{1000 + i * 60000},{o:.2f},{h:.2f},{l:.2f},{c:.2f},{v:.2f}")
        price = c
    return "\n".join(lines)


class TestVolatilityMetrics:
    def test_insufficient_data(self):
        csv = "timestamp,open,high,low,close,volume\n1000,100,105,95,102,500"
        result = get_volatility_metrics(csv)
        assert result["volatility_regime"] == "Normal"
        assert result["atr_14"] is None

    def test_sufficient_data(self):
        csv = _make_kline_csv(250)
        result = get_volatility_metrics(csv)
        assert result["atr_14"] is not None
        assert result["volatility_regime"] in ("Low", "Normal", "High")
        assert result["bb_width"] is not None


class TestMarketRegime:
    def test_insufficient_data(self):
        csv = _make_kline_csv(50)
        result = get_market_regime(csv)
        assert result["regime"] == "Unknown"

    def test_sufficient_data(self):
        csv = _make_kline_csv(250)
        result = get_market_regime(csv)
        assert result["regime"] in ("Trending", "Ranging", "Transitional")
        assert result["ema_20"] is not None
        assert result["ema_50"] is not None
        assert result["ema_200"] is not None


class TestLiquidationPrice:
    def test_long_position(self):
        result = estimate_liquidation_price(100, 10, "long")
        assert result["liq_price"] is not None
        assert result["liq_price"] < 100
        assert result["distance_pct"] > 0

    def test_short_position(self):
        result = estimate_liquidation_price(100, 10, "short")
        assert result["liq_price"] is not None
        assert result["liq_price"] > 100

    def test_invalid_inputs(self):
        result = estimate_liquidation_price(100, 0, "long")
        assert result["liq_price"] is None

    def test_higher_leverage_closer_liquidation(self):
        r5 = estimate_liquidation_price(100, 5, "long")
        r20 = estimate_liquidation_price(100, 20, "long")
        assert r20["distance_pct"] < r5["distance_pct"]


class TestFundingCostProjection:
    def test_normal_rates(self):
        csv = "timestamp,rate\n1,0.0001\n2,0.00015\n3,0.0001"
        result = project_funding_cost(csv, hold_intervals=21)
        assert result["severity"] == "normal"
        assert result["total_rate"] is not None

    def test_elevated_rates(self):
        csv = "timestamp,rate\n1,0.0005\n2,0.0005\n3,0.0005"
        result = project_funding_cost(csv)
        assert result["severity"] == "elevated"

    def test_extreme_rates(self):
        csv = "timestamp,rate\n1,0.002\n2,0.002\n3,0.002"
        result = project_funding_cost(csv)
        assert result["severity"] == "extreme"

    def test_empty_rates(self):
        csv = "timestamp,rate"
        result = project_funding_cost(csv)
        assert result["total_rate"] is None
