"""Composite scoring logic for TA pre-filter.

Takes indicator outputs and produces a 0-100 opportunity score.
Score >= threshold means "proceed with LLM analysis".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ScoreBreakdown:
    trend: float  # 0-25
    momentum: float  # 0-25
    volatility: float  # 0-20
    volume: float  # 0-15
    derivatives: float  # 0-15

    @property
    def total(self) -> float:
        return self.trend + self.momentum + self.volatility + self.volume + self.derivatives

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trend": round(self.trend, 1),
            "momentum": round(self.momentum, 1),
            "volatility": round(self.volatility, 1),
            "volume": round(self.volume, 1),
            "derivatives": round(self.derivatives, 1),
            "total": round(self.total, 1),
        }


def score_trend(
    adx_value: float,
    ema_cross_bullish: bool,
    ema_cross_bearish: bool,
    supertrend_direction: int,
    structure_trend: str,
) -> float:
    """Score trend strength (0-25). Rewards clear directional trends."""
    score = 0.0

    # ADX: strong trend > 25
    if adx_value > 40:
        score += 10
    elif adx_value > 25:
        score += 6
    elif adx_value > 20:
        score += 3

    # EMA crossover signal
    if ema_cross_bullish or ema_cross_bearish:
        score += 5

    # SuperTrend alignment with structure trend
    # Only award points when SuperTrend direction confirms the structure
    if structure_trend == "bullish" and supertrend_direction == 1:
        score += 4
    elif structure_trend == "bearish" and supertrend_direction == -1:
        score += 4

    # Market structure
    if structure_trend in ("bullish", "bearish"):
        score += 6
    elif structure_trend == "ranging":
        score += 2

    return min(25.0, score)


def score_momentum(
    rsi_value: float,
    macd_histogram: float,
    macd_cross_recent: bool,
    macd_histogram_growing: bool,
    stoch_k: float,
    stoch_d: float,
) -> float:
    """Score momentum signals (0-25). Rewards oversold/overbought extremes and crossovers."""
    score = 0.0

    # RSI extremes (opportunity zones)
    if rsi_value < 30 or rsi_value > 70:
        score += 8
    elif rsi_value < 40 or rsi_value > 60:
        score += 4

    # MACD cross is the primary signal; expanding histogram is secondary
    if macd_cross_recent:
        score += 5
    elif macd_histogram_growing:
        score += 3

    # Stochastic in extreme + crossover
    if stoch_k < 20 or stoch_k > 80:
        score += 6
    if (stoch_k < 20 and stoch_k > stoch_d) or (stoch_k > 80 and stoch_k < stoch_d):
        score += 6

    return min(25.0, score)


def score_volatility(
    bb_width: float,
    bb_width_percentile: float,
    atr_pct: float,
    price_vs_bb: str,
) -> float:
    """Score volatility opportunity (0-20). Rewards squeezes and band breaks."""
    score = 0.0

    # Bollinger squeeze (low width percentile = potential breakout)
    if bb_width_percentile < 20:
        score += 8
    elif bb_width_percentile < 40:
        score += 4

    # Price at band extremes
    if price_vs_bb in ("above_upper", "below_lower"):
        score += 7
    elif price_vs_bb in ("near_upper", "near_lower"):
        score += 4

    # ATR% — higher volatility = more opportunity
    if atr_pct > 5:
        score += 5
    elif atr_pct > 3:
        score += 3

    return min(20.0, score)


def score_volume(
    obv_trend: str,
    volume_spike: bool,
    vp_position: str,
    vp_distance_pct: float,
) -> float:
    """Score volume signals (0-15)."""
    score = 0.0

    # OBV trend — only meaningful when combined with volume spike or VP signal
    # (OBV is always "bullish" or "bearish" so it serves as a direction qualifier)
    has_volume_event = volume_spike or abs(vp_distance_pct) > 1.5
    if obv_trend in ("bullish", "bearish") and has_volume_event:
        score += 5

    # Volume spike
    if volume_spike:
        score += 5

    # Volume profile positioning
    if abs(vp_distance_pct) > 3:
        score += 5
    elif abs(vp_distance_pct) > 1.5:
        score += 3

    return min(15.0, score)


def score_derivatives(
    funding_rate: float | None,
    oi_change_pct: float | None,
) -> float:
    """Score derivatives signals (0-15). Rewards extreme funding and OI divergences."""
    score = 0.0

    if funding_rate is not None:
        # Extreme funding = potential squeeze
        if abs(funding_rate) > 0.01:
            score += 8
        elif abs(funding_rate) > 0.005:
            score += 5
        elif abs(funding_rate) > 0.001:
            score += 2

    if oi_change_pct is not None:
        # Large OI changes signal positioning
        if abs(oi_change_pct) > 10:
            score += 7
        elif abs(oi_change_pct) > 5:
            score += 4
        elif abs(oi_change_pct) > 2:
            score += 2

    return min(15.0, score)


def compute_composite_score(
    trend_inputs: dict,
    momentum_inputs: dict,
    volatility_inputs: dict,
    volume_inputs: dict,
    derivatives_inputs: dict,
) -> ScoreBreakdown:
    return ScoreBreakdown(
        trend=score_trend(**trend_inputs),
        momentum=score_momentum(**momentum_inputs),
        volatility=score_volatility(**volatility_inputs),
        volume=score_volume(**volume_inputs),
        derivatives=score_derivatives(**derivatives_inputs),
    )
