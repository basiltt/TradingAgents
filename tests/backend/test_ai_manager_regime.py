"""Tests for enhanced market regime classifier."""
import pytest

from backend.services.ai_manager_regime import compute_regime


class TestComputeRegime:
    def test_trending_up(self):
        indicators = {
            "adx_14": 32.0,
            "ema_50_distance_pct": 0.02,
            "atr_ratio": 1.1,
            "bbw_percentile": 0.6,
        }
        mtf = {
            "per_tf": {
                "1h": {"trend": "bullish", "ema_alignment": 0.7},
                "4h": {"trend": "bullish", "ema_alignment": 0.8},
            },
            "trend_alignment": 0.75,
        }
        result = compute_regime(indicators, mtf)
        assert result["regime"] == "trending_up"
        assert result["regime_detail"]["confidence"] > 0.5
        assert "adx" in result["regime_detail"]

    def test_trending_down(self):
        indicators = {"adx_14": 28.0, "ema_50_distance_pct": -0.03, "atr_ratio": 1.0, "bbw_percentile": 0.5}
        mtf = {"per_tf": {"1h": {"trend": "bearish"}, "4h": {"trend": "bearish"}}, "trend_alignment": -0.7}
        result = compute_regime(indicators, mtf)
        assert result["regime"] == "trending_down"

    def test_ranging(self):
        indicators = {"adx_14": 15.0, "ema_50_distance_pct": 0.001, "atr_ratio": 0.8, "bbw_percentile": 0.4}
        mtf = {"per_tf": {"1h": {"trend": "mixed"}, "4h": {"trend": "mixed"}}, "trend_alignment": 0.1}
        result = compute_regime(indicators, mtf)
        assert result["regime"] == "ranging"

    def test_volatile(self):
        indicators = {"adx_14": 30.0, "ema_50_distance_pct": 0.05, "atr_ratio": 2.5, "bbw_percentile": 0.9}
        mtf = {"per_tf": {"1h": {"trend": "bullish"}, "4h": {"trend": "mixed"}}, "trend_alignment": 0.3}
        result = compute_regime(indicators, mtf)
        assert result["regime"] == "volatile"

    def test_compression(self):
        indicators = {"adx_14": 12.0, "ema_50_distance_pct": 0.0, "atr_ratio": 0.5, "bbw_percentile": 0.05}
        mtf = {"per_tf": {"1h": {"trend": "mixed"}, "4h": {"trend": "mixed"}}, "trend_alignment": 0.0}
        result = compute_regime(indicators, mtf)
        assert result["regime"] == "compression"

    def test_empty_inputs_defaults_to_ranging(self):
        result = compute_regime({}, {})
        assert result["regime"] == "ranging"

    def test_regime_detail_structure(self):
        indicators = {"adx_14": 30.0, "ema_50_distance_pct": 0.02, "atr_ratio": 1.1, "bbw_percentile": 0.6}
        mtf = {"per_tf": {"1h": {"trend": "bullish"}, "4h": {"trend": "bullish"}}, "trend_alignment": 0.7}
        result = compute_regime(indicators, mtf)
        detail = result["regime_detail"]
        assert "confidence" in detail
        assert "adx" in detail
        assert "atr_ratio" in detail
        assert "bbw_percentile" in detail
        assert 0.0 <= detail["confidence"] <= 1.0
