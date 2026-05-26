"""AI Manager Signal Evaluator — Phase 3 Task 3.4.

Lightweight non-LLM urgency classifier based on market signals.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PNL_VELOCITY_THRESHOLD = 0.02  # 2% in 30s
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
    ) -> str:
        """Returns 'FAST', 'STANDARD', or 'DEEP'."""
        if not positions:
            return "STANDARD"

        indicators = indicators or {}
        peak_pnl = peak_pnl or {}
        fast_signals = 0
        conflicting = False

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue

            # Per-symbol urgent cooldown
            now = time.monotonic()
            last = self._last_urgent.get(symbol, 0.0)
            if now - last < _SYMBOL_URGENT_COOLDOWN_S:
                continue

            sym_indicators = indicators.get(symbol, {})
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

        if fast_signals > 0:
            return "FAST"
        if conflicting:
            return "DEEP"
        return "STANDARD"

    def _check_urgent_signals(self, position: Dict[str, Any], indicators: Dict[str, Any]) -> bool:
        """Check if position has urgent signals requiring immediate evaluation."""
        # PnL velocity: >2% in 30s
        pnl_velocity = indicators.get("pnl_velocity_30s")
        if pnl_velocity is not None and abs(pnl_velocity) >= _PNL_VELOCITY_THRESHOLD:
            return True

        # RSI divergence: crosses 70/30 threshold (require both current and previous)
        rsi = indicators.get("rsi_14")
        prev_rsi = indicators.get("prev_rsi_14")
        if rsi is not None and prev_rsi is not None:
            if (prev_rsi < _RSI_UPPER and rsi >= _RSI_UPPER) or (prev_rsi > _RSI_LOWER and rsi <= _RSI_LOWER):
                return True

        # Funding rate flip
        funding = indicators.get("funding_rate")
        prev_funding = indicators.get("prev_funding_rate")
        if funding is not None and prev_funding is not None:
            if funding != 0 and prev_funding != 0 and (funding > 0) != (prev_funding > 0):
                return True

        # Volatility spike: 1m candle body > 2x ATR
        candle_body = indicators.get("candle_1m_body")
        atr = indicators.get("atr_14")
        if candle_body is not None and atr is not None and atr > 0:
            if abs(candle_body) > _ATR_MULTIPLIER * atr:
                return True

        return False
