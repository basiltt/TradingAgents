"""Tests for the TA pre-filter scoring logic."""

from tradingagents.ta_prefilter.scorer import (
    compute_composite_score,
    score_trend,
    score_momentum,
    score_volatility,
    score_volume,
    score_derivatives,
)


class TestScoreTrend:
    def test_strong_trend(self):
        score = score_trend(adx_value=45, ema_cross_bullish=True, ema_cross_bearish=False, supertrend_direction=1, structure_trend="bullish")
        assert score == 25  # capped at max

    def test_weak_trend(self):
        score = score_trend(adx_value=15, ema_cross_bullish=False, ema_cross_bearish=False, supertrend_direction=0, structure_trend="ranging")
        assert score == 2  # only ranging gives 2

    def test_no_trend(self):
        score = score_trend(adx_value=10, ema_cross_bullish=False, ema_cross_bearish=False, supertrend_direction=0, structure_trend="unknown")
        assert score == 0


class TestScoreMomentum:
    def test_extreme_rsi_with_stoch(self):
        score = score_momentum(rsi_value=25, macd_histogram=0.5, macd_cross_recent=True, macd_histogram_growing=True, stoch_k=15, stoch_d=20)
        # RSI<30=8, MACD cross=5, stoch<20=6, stoch crossover (k<20 and k<d doesn't trigger, k>d needed)
        assert score >= 19

    def test_neutral(self):
        score = score_momentum(rsi_value=50, macd_histogram=0.0, macd_cross_recent=False, macd_histogram_growing=False, stoch_k=50, stoch_d=50)
        assert score == 0

    def test_histogram_growing_without_cross(self):
        score = score_momentum(rsi_value=50, macd_histogram=0.5, macd_cross_recent=False, macd_histogram_growing=True, stoch_k=50, stoch_d=50)
        assert score == 3

    def test_histogram_not_growing_without_cross(self):
        score = score_momentum(rsi_value=50, macd_histogram=0.5, macd_cross_recent=False, macd_histogram_growing=False, stoch_k=50, stoch_d=50)
        assert score == 0


class TestScoreVolatility:
    def test_squeeze_with_band_break(self):
        score = score_volatility(bb_width=0.02, bb_width_percentile=10, atr_pct=6, price_vs_bb="above_upper")
        # percentile<20=8, above_upper=7, atr>5=5 = 20 (capped)
        assert score == 20

    def test_calm_middle(self):
        score = score_volatility(bb_width=0.05, bb_width_percentile=60, atr_pct=1, price_vs_bb="middle")
        assert score == 0


class TestScoreVolume:
    def test_spike_with_divergence(self):
        score = score_volume(obv_trend="bullish", volume_spike=True, vp_position="above_poc", vp_distance_pct=5.0)
        assert score == 15  # 5+5+5

    def test_no_signal(self):
        score = score_volume(obv_trend="neutral", volume_spike=False, vp_position="at_poc", vp_distance_pct=0.5)
        assert score == 0


class TestScoreDerivatives:
    def test_extreme_funding(self):
        score = score_derivatives(funding_rate=0.02, oi_change_pct=15)
        assert score == 15  # 8 + 7

    def test_none_values(self):
        score = score_derivatives(funding_rate=None, oi_change_pct=None)
        assert score == 0


class TestCompositeScore:
    def test_all_max(self):
        breakdown = compute_composite_score(
            trend_inputs={"adx_value": 50, "ema_cross_bullish": True, "ema_cross_bearish": False, "supertrend_direction": 1, "structure_trend": "bullish"},
            momentum_inputs={"rsi_value": 25, "macd_histogram": 1.0, "macd_cross_recent": True, "macd_histogram_growing": True, "stoch_k": 15, "stoch_d": 10},
            volatility_inputs={"bb_width": 0.01, "bb_width_percentile": 5, "atr_pct": 8, "price_vs_bb": "below_lower"},
            volume_inputs={"obv_trend": "bullish", "volume_spike": True, "vp_position": "below_poc", "vp_distance_pct": -5.0},
            derivatives_inputs={"funding_rate": 0.02, "oi_change_pct": 15},
        )
        assert breakdown.total == 100

    def test_all_min(self):
        breakdown = compute_composite_score(
            trend_inputs={"adx_value": 10, "ema_cross_bullish": False, "ema_cross_bearish": False, "supertrend_direction": 0, "structure_trend": "unknown"},
            momentum_inputs={"rsi_value": 50, "macd_histogram": 0, "macd_cross_recent": False, "macd_histogram_growing": False, "stoch_k": 50, "stoch_d": 50},
            volatility_inputs={"bb_width": 0.05, "bb_width_percentile": 60, "atr_pct": 1, "price_vs_bb": "middle"},
            volume_inputs={"obv_trend": "neutral", "volume_spike": False, "vp_position": "at_poc", "vp_distance_pct": 0.5},
            derivatives_inputs={"funding_rate": None, "oi_change_pct": None},
        )
        assert breakdown.total == 0

    def test_threshold_boundary(self):
        breakdown = compute_composite_score(
            trend_inputs={"adx_value": 26, "ema_cross_bullish": False, "ema_cross_bearish": False, "supertrend_direction": 1, "structure_trend": "ranging"},
            momentum_inputs={"rsi_value": 35, "macd_histogram": 0.1, "macd_cross_recent": False, "macd_histogram_growing": True, "stoch_k": 50, "stoch_d": 50},
            volatility_inputs={"bb_width": 0.03, "bb_width_percentile": 35, "atr_pct": 3.5, "price_vs_bb": "near_lower"},
            volume_inputs={"obv_trend": "bearish", "volume_spike": False, "vp_position": "below_poc", "vp_distance_pct": -2.0},
            derivatives_inputs={"funding_rate": 0.002, "oi_change_pct": 3},
        )
        # Should produce a moderate score around 40-50
        assert 20 <= breakdown.total <= 60
