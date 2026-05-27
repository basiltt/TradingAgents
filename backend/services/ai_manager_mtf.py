"""AI Manager Multi-Timeframe Analysis.

Provides trend context from multiple timeframes (5m, 15m, 1h, 4h).
Higher timeframes act as a filter for AI decisions.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

_TF_WEIGHTS = {"5m": 0.1, "15m": 0.2, "1h": 0.35, "4h": 0.35}


class MultiTimeframeAnalyzer:
    """Stateless MTF signal computer."""

    def compute_signal(self, symbol: str, klines: Dict[str, List]) -> Dict[str, Any]:
        """Compute MTF signal from kline data per timeframe.

        klines: {"5m": [[ts, o, h, l, c, vol], ...], "15m": [...], ...}
        Returns dict matching state["mtf"] structure.
        """
        if not klines:
            return self._empty_signal()

        per_tf = {}
        weighted_sum = 0.0
        weight_total = 0.0

        for tf, weight in _TF_WEIGHTS.items():
            data = klines.get(tf)
            if not data or len(data) < 10:
                continue
            tf_signal = self._analyze_timeframe(data)
            per_tf[tf] = tf_signal
            weighted_sum += tf_signal["ema_alignment"] * weight
            weight_total += weight

        if weight_total == 0:
            return self._empty_signal()

        trend_alignment = weighted_sum / weight_total
        trend_strength = self._compute_trend_strength(per_tf)

        if trend_alignment > 0.3:
            dominant = "bullish"
        elif trend_alignment < -0.3:
            dominant = "bearish"
        else:
            dominant = "mixed"

        key_levels = self._find_key_levels(klines)

        available_tf_ratio = weight_total / sum(_TF_WEIGHTS.values())
        confidence = round(available_tf_ratio * min(1.0, abs(trend_alignment) + 0.3), 4)

        return {
            "trend_alignment": round(trend_alignment, 4),
            "dominant_trend": dominant,
            "trend_strength": round(trend_strength, 4),
            "confidence": confidence,
            "key_levels": key_levels,
            "divergences": [],
            "per_tf": per_tf,
        }

    def _analyze_timeframe(self, klines: List) -> Dict[str, Any]:
        closes = [float(k[4]) for k in klines if len(k) > 4]
        if len(closes) < 10:
            return {"trend": "mixed", "rsi": 50.0, "ema_alignment": 0.0}
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        rsi = self._rsi(closes, 14)

        if ema21 == 0:
            return {"trend": "mixed", "rsi": round(rsi, 1), "ema_alignment": 0.0}

        if ema9 > ema21:
            trend = "bullish"
            alignment = min(1.0, (ema9 - ema21) / ema21 * 100)
        elif ema9 < ema21:
            trend = "bearish"
            alignment = max(-1.0, (ema9 - ema21) / ema21 * 100)
        else:
            trend = "mixed"
            alignment = 0.0

        return {"trend": trend, "rsi": round(rsi, 1), "ema_alignment": round(alignment, 4)}

    def _compute_trend_strength(self, per_tf: Dict[str, Dict]) -> float:
        if not per_tf:
            return 0.0
        alignments = [abs(tf["ema_alignment"]) for tf in per_tf.values()]
        return min(1.0, sum(alignments) / len(alignments))

    def _find_key_levels(self, klines: Dict[str, List]) -> List[Dict[str, Any]]:
        levels = []
        for tf, data in klines.items():
            if not data or len(data) < 20:
                continue
            highs = [float(k[2]) for k in data[-50:] if len(k) > 4]
            lows = [float(k[3]) for k in data[-50:] if len(k) > 4]
            if not highs or not lows:
                continue
            current = float(data[-1][4]) if len(data[-1]) > 4 else 0.0
            if current == 0:
                continue

            for i in range(2, len(highs) - 2):
                if highs[i] == max(highs[i-2:i+3]):
                    dist = abs(highs[i] - current) / current * 100
                    if dist < 3.0:
                        levels.append({"price": highs[i], "timeframe": tf, "type": "resistance", "distance_pct": round(dist, 2)})
                if lows[i] == min(lows[i-2:i+3]):
                    dist = abs(lows[i] - current) / current * 100
                    if dist < 3.0:
                        levels.append({"price": lows[i], "timeframe": tf, "type": "support", "distance_pct": round(dist, 2)})

        levels.sort(key=lambda x: x["distance_pct"])
        return levels[:10]

    def _ema(self, data: List[float], period: int) -> float:
        if len(data) < period:
            return data[-1] if data else 0.0
        multiplier = 2.0 / (period + 1)
        ema = sum(data[:period]) / period
        for val in data[period:]:
            ema = (val - ema) * multiplier + ema
        return ema

    def _rsi(self, data: List[float], period: int = 14) -> float:
        if len(data) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(data)):
            diff = data[i] - data[i - 1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _empty_signal(self) -> Dict[str, Any]:
        return {
            "trend_alignment": 0.0,
            "dominant_trend": "mixed",
            "trend_strength": 0.0,
            "confidence": 0.0,
            "key_levels": [],
            "divergences": [],
            "per_tf": {},
        }
