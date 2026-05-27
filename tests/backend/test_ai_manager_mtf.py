"""Tests for multi-timeframe analysis module."""
import pytest

from backend.services.ai_manager_mtf import MultiTimeframeAnalyzer


class TestMultiTimeframeAnalyzer:
    def test_compute_signal_bullish(self):
        klines = {
            "5m": _make_uptrend_klines(50),
            "15m": _make_uptrend_klines(50),
            "1h": _make_uptrend_klines(50),
            "4h": _make_uptrend_klines(50),
        }
        analyzer = MultiTimeframeAnalyzer()
        result = analyzer.compute_signal("BTCUSDT", klines)
        assert result["trend_alignment"] > 0.5
        assert result["dominant_trend"] == "bullish"
        assert "per_tf" in result
        assert "5m" in result["per_tf"]

    def test_compute_signal_mixed(self):
        klines = {
            "5m": _make_uptrend_klines(50),
            "15m": _make_downtrend_klines(50),
            "1h": _make_uptrend_klines(50),
            "4h": _make_downtrend_klines(50),
        }
        analyzer = MultiTimeframeAnalyzer()
        result = analyzer.compute_signal("BTCUSDT", klines)
        # With balanced mixed timeframes, should be close to zero
        assert abs(result["trend_alignment"]) < 0.3
        assert result["dominant_trend"] == "mixed"

    def test_compute_signal_empty_klines(self):
        analyzer = MultiTimeframeAnalyzer()
        result = analyzer.compute_signal("BTCUSDT", {})
        assert result["trend_alignment"] == 0.0
        assert result["dominant_trend"] == "mixed"
        assert result["trend_strength"] == 0.0

    def test_key_levels_detected(self):
        klines = {"1h": _make_ranging_klines(100)}
        analyzer = MultiTimeframeAnalyzer()
        result = analyzer.compute_signal("BTCUSDT", klines)
        assert "key_levels" in result

    def test_partial_timeframes(self):
        klines = {"1h": _make_uptrend_klines(50)}
        analyzer = MultiTimeframeAnalyzer()
        result = analyzer.compute_signal("BTCUSDT", klines)
        assert result["trend_alignment"] != 0.0


def _make_uptrend_klines(n: int) -> list:
    base = 50000.0
    # More aggressive uptrend: +100 per candle
    return [[i * 60000, base + i * 100, base + i * 100 + 200, base + i * 100 - 50, base + i * 100 + 150, 100.0] for i in range(n)]


def _make_downtrend_klines(n: int) -> list:
    base = 60000.0
    # More aggressive downtrend: -100 per candle
    return [[i * 60000, base - i * 100, base - i * 100 + 50, base - i * 100 - 200, base - i * 100 - 150, 100.0] for i in range(n)]


def _make_ranging_klines(n: int) -> list:
    import math
    base = 55000.0
    return [[i * 60000, base + math.sin(i * 0.3) * 200, base + 250, base - 250, base + math.sin(i * 0.3 + 0.5) * 200, 100.0] for i in range(n)]
