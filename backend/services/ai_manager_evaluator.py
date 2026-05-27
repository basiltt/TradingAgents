"""AI Manager Signal Evaluator — Phase 3 Task 3.4.

Lightweight non-LLM urgency classifier based on market signals.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PNL_VELOCITY_THRESHOLD = 0.02  # 2% in 30s
_EMERGENCY_PNL_VELOCITY_THRESHOLD = 0.05  # 5% in 30s — triggers non-LLM emergency close
_RSI_UPPER = 70
_RSI_LOWER = 30
_ATR_MULTIPLIER = 2.0
_SYMBOL_URGENT_COOLDOWN_S = 15.0


class AIManagerEvaluator:
    """Classifies urgency for each position evaluation."""

    def __init__(self):
        self._last_urgent: Dict[str, float] = {}

    def classify_urgency(
        self,
        positions: List[Dict[str, Any]],
        indicators: Optional[Dict[str, Any]] = None,
        peak_pnl: Optional[Dict[str, float]] = None,
        emergency_pnl_velocity_pct: float = 0.05,
        correlation: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Returns 'EMERGENCY', 'FAST', 'STANDARD', or 'DEEP'.

        EMERGENCY: extreme signals requiring immediate non-LLM close.
        """
        if not positions:
            return "STANDARD"

        indicators = indicators or {}
        peak_pnl = peak_pnl or {}
        fast_signals = 0
        emergency_signals = 0
        conflicting = False

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue

            sym_indicators = indicators.get(symbol, {})

            # Check for EMERGENCY-level signals (no cooldown — always evaluate)
            if self.check_emergency_signals(pos, sym_indicators, emergency_pnl_velocity_pct):
                emergency_signals += 1
                continue

            # Per-symbol urgent cooldown
            now = time.monotonic()
            last = self._last_urgent.get(symbol, 0.0)
            if now - last < _SYMBOL_URGENT_COOLDOWN_S:
                continue

            urgent = self._check_urgent_signals(pos, sym_indicators)

            # Drawdown-from-peak urgency: if profit dropped >40% from peak, it's urgent
            if not urgent and symbol in peak_pnl:
                peak = peak_pnl[symbol]
                if peak > 0:
                    try:
                        current = float(pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0)))
                        if current < peak and ((peak - current) / peak) > 0.4:
                            urgent = True
                    except (ValueError, TypeError):
                        pass

            if urgent:
                fast_signals += 1
                self._last_urgent[symbol] = now

            # Check for conflicting signals (both bullish and bearish)
            if sym_indicators.get("conflicting"):
                conflicting = True

        if emergency_signals > 0:
            return "EMERGENCY"
        # Correlation-based escalation
        if correlation and emergency_signals == 0:
            for cluster in correlation.get("clusters", []):
                if cluster.get("combined_pnl_pct", 0) < -2.0:
                    return "FAST"
        if fast_signals > 0:
            return "FAST"
        if conflicting:
            return "DEEP"
        return "STANDARD"

    def check_emergency_signals(
        self, position: Dict[str, Any], indicators: Dict[str, Any], velocity_threshold: float
    ) -> bool:
        """Check for extreme signals that bypass LLM entirely."""
        pnl_velocity = indicators.get("pnl_velocity_30s")
        if pnl_velocity is not None:
            try:
                upnl = float(position.get("unrealisedPnl", position.get("unrealized_pnl", 0)))
                vel = float(pnl_velocity)
                if upnl < 0 and abs(vel) >= velocity_threshold:
                    # vel is price velocity: negative = price dropping, positive = price rising
                    # LONG loses when price drops (vel < 0), SHORT loses when price rises (vel > 0)
                    side = position.get("side", "")
                    if (side == "Buy" and vel < 0) or (side == "Sell" and vel > 0):
                        return True
            except (ValueError, TypeError):
                pass
        return False

    def _check_urgent_signals(self, position: Dict[str, Any], indicators: Dict[str, Any]) -> bool:
        """Check if position has urgent signals requiring immediate evaluation."""
        # PnL velocity: >2% in 30s
        pnl_velocity = indicators.get("pnl_velocity_30s")
        try:
            if pnl_velocity is not None and abs(float(pnl_velocity)) >= _PNL_VELOCITY_THRESHOLD:
                return True
        except (TypeError, ValueError):
            pass

        # RSI divergence: crosses 70/30 threshold (require both current and previous)
        rsi = indicators.get("rsi_14")
        prev_rsi = indicators.get("prev_rsi_14")
        try:
            if rsi is not None and prev_rsi is not None:
                rsi_f, prev_f = float(rsi), float(prev_rsi)
                if (prev_f < _RSI_UPPER and rsi_f >= _RSI_UPPER) or (prev_f > _RSI_LOWER and rsi_f <= _RSI_LOWER):
                    return True
        except (TypeError, ValueError):
            pass

        # Funding rate flip
        funding = indicators.get("funding_rate")
        prev_funding = indicators.get("prev_funding_rate")
        try:
            if funding is not None and prev_funding is not None:
                f_f, pf_f = float(funding), float(prev_funding)
                if f_f != 0 and pf_f != 0 and (f_f > 0) != (pf_f > 0):
                    return True
        except (TypeError, ValueError):
            pass

        # Volatility spike: 1m candle body > 2x ATR
        candle_body = indicators.get("candle_1m_body")
        atr = indicators.get("atr_14")
        try:
            if candle_body is not None and atr is not None:
                atr_f = float(atr)
                if atr_f > 0 and abs(float(candle_body)) > _ATR_MULTIPLIER * atr_f:
                    return True
        except (TypeError, ValueError):
            pass

        return False
