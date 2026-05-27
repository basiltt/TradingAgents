"""AI Manager Multi-Indicator Regime Classifier.

Replaces the naive _detect_regime() with a proper multi-indicator approach
using ADX, Bollinger Bandwidth, ATR ratio, and MTF alignment.
"""

from __future__ import annotations

from typing import Any, Dict


def compute_regime(indicators: Dict[str, Any], mtf_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute market regime from indicators and multi-timeframe data.

    Returns dict with 'regime' (str) and 'regime_detail' (dict).
    """
    adx = _safe_float(indicators.get("adx_14"), 15.0)
    ema_dist = _safe_float(indicators.get("ema_50_distance_pct"), 0.0)
    atr_ratio = _safe_float(indicators.get("atr_ratio"), 1.0)
    bbw_pct = _safe_float(indicators.get("bbw_percentile"), 0.5)
    trend_alignment = _safe_float(mtf_data.get("trend_alignment"), 0.0)

    regime = _classify(adx, ema_dist, atr_ratio, bbw_pct, trend_alignment, mtf_data)
    confidence = _compute_confidence(regime, adx, atr_ratio, bbw_pct, trend_alignment)

    return {
        "regime": regime,
        "regime_detail": {
            "confidence": confidence,
            "adx": adx,
            "atr_ratio": atr_ratio,
            "bbw_percentile": bbw_pct,
            "trend_alignment": trend_alignment,
            "ema_distance_pct": ema_dist,
            "duration_candles": 0,
            "transition_probability": round(1.0 - confidence, 4),
            "dominant_timeframe": mtf_data.get("per_tf", {}) and _get_dominant_tf(mtf_data) or "unknown",
        },
    }


def _classify(
    adx: float, ema_dist: float, atr_ratio: float, bbw_pct: float,
    trend_alignment: float, mtf_data: Dict[str, Any],
) -> str:
    if atr_ratio >= 2.0:
        return "volatile"
    if bbw_pct < 0.1 and atr_ratio < 0.7:
        return "compression"
    if adx > 25:
        if trend_alignment > 0.4 or ema_dist > 0.01:
            return "trending_up"
        if trend_alignment < -0.4 or ema_dist < -0.01:
            return "trending_down"
    return "ranging"


def _compute_confidence(
    regime: str, adx: float, atr_ratio: float, bbw_pct: float, trend_alignment: float,
) -> float:
    if regime == "volatile":
        return min(1.0, (atr_ratio - 1.5) / 1.5)
    if regime == "compression":
        return min(1.0, (0.15 - bbw_pct) / 0.15) if bbw_pct < 0.15 else 0.5
    if regime in ("trending_up", "trending_down"):
        adx_score = min(1.0, (adx - 20) / 30)
        align_score = min(1.0, abs(trend_alignment))
        return (adx_score + align_score) / 2
    return max(0.3, 1.0 - adx / 40)


def _get_dominant_tf(mtf_data: Dict[str, Any]) -> str:
    per_tf = mtf_data.get("per_tf", {})
    if not per_tf:
        return "unknown"
    best_tf = max(per_tf.items(), key=lambda x: abs(x[1].get("ema_alignment", 0)), default=("unknown", {}))
    return best_tf[0]


def _safe_float(val: Any, default: float) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
