"""AI Manager Event-Driven Trigger Detector.

Lightweight, non-LLM module that determines when an LLM evaluation should fire
based on market events rather than a fixed timer. Runs on every WebSocket tick
with negligible overhead.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _compute_regime_label(indicators: Dict[str, Any]) -> Optional[str]:
    """Compute regime from a single symbol's indicators (lightweight).

    Returns None if indicators lack the fields needed for meaningful classification.
    """
    if not indicators:
        return None
    # Require at least one regime-critical field to avoid false defaults
    if "adx_14" not in indicators and "atr_ratio" not in indicators:
        return None
    try:
        from backend.services.ai_manager_regime import compute_regime
        result = compute_regime(indicators, {})
        return result.get("regime") if result else None
    except Exception:
        return None


class EventTriggerDetector:
    """Detects meaningful market events that warrant an LLM evaluation.

    Tracks state since the last evaluation and fires when any configured
    threshold is breached. Designed to replace fixed-interval polling with
    event-driven LLM calls + a periodic safety net.
    """

    def __init__(
        self,
        price_move_pct: float = 1.5,
        drawdown_from_peak_pct: float = 25.0,
        pnl_velocity_pct: float = 1.5,
        volume_anomaly_multiplier: float = 3.0,
        staleness_alarm_s: int = 600,
        funding_rate_threshold: float = 0.0005,
    ):
        self._price_move_pct = price_move_pct
        self._drawdown_from_peak_pct = drawdown_from_peak_pct
        self._pnl_velocity_pct = pnl_velocity_pct
        self._volume_anomaly_multiplier = volume_anomaly_multiplier
        self._staleness_alarm_s = staleness_alarm_s
        self._funding_rate_threshold = funding_rate_threshold

        # State tracked since last evaluation
        self._last_eval_prices: Dict[str, float] = {}
        self._last_eval_time: float = time.monotonic()
        self._last_regime: Optional[str] = None
        self._last_eval_funding: Dict[str, float] = {}
        self._last_eval_volume: Dict[str, float] = {}
        self._last_regime_check_time: float = 0.0
        self._last_trigger_time: float = 0.0
        self._min_trigger_interval_s: float = 15.0

    _REGIME_CHECK_COOLDOWN_S = 30.0

    def check_triggers(
        self,
        positions: List[Dict[str, Any]],
        indicators: Optional[Dict[str, Any]] = None,
        peak_pnl: Optional[Dict[str, float]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Check all event triggers against current market state.

        Returns (should_fire, reason). May update internal cooldown timers.
        Call mark_evaluated() after the LLM evaluation completes.
        """
        indicators = indicators or {}
        peak_pnl = peak_pnl or {}

        # 1. Staleness alarm — no eval for too long (NEVER suppressed by debounce)
        elapsed = time.monotonic() - self._last_eval_time
        if elapsed >= self._staleness_alarm_s:
            return True, f"staleness_alarm ({int(elapsed)}s since last eval)"

        # Debounce: suppress non-safety triggers for a minimum interval after last trigger fired
        now = time.monotonic()
        if (now - self._last_trigger_time) < self._min_trigger_interval_s:
            return False, None

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue

            # NEW POSITION: symbol not in baseline → trigger immediate evaluation
            if symbol not in self._last_eval_prices and self._last_eval_prices:
                return True, f"new_position ({symbol})"

            # 2. Price move from last-evaluated price
            try:
                mark_price = float(pos.get("markPrice", pos.get("mark_price", 0)))
                if mark_price > 0 and symbol in self._last_eval_prices:
                    last_price = self._last_eval_prices[symbol]
                    if last_price > 0:
                        move_pct = abs(mark_price - last_price) / last_price * 100
                        if move_pct >= self._price_move_pct:
                            return True, f"price_move ({symbol}: {move_pct:.2f}%)"
            except (ValueError, TypeError):
                pass

            sym_indicators = indicators.get(symbol, {})

            # 3. PnL velocity (below emergency threshold but notable)
            try:
                vel = sym_indicators.get("pnl_velocity_30s")
                if vel is not None and abs(float(vel)) >= self._pnl_velocity_pct / 100:
                    return True, f"pnl_velocity ({symbol}: {float(vel)*100:.2f}%/30s)"
            except (ValueError, TypeError):
                pass

            # 4. Drawdown from peak
            if symbol in peak_pnl:
                peak = peak_pnl[symbol]
                if peak > 0:
                    try:
                        current = float(
                            pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0))
                        )
                        if current < peak:
                            drawdown_pct = (peak - current) / peak * 100
                            if drawdown_pct >= self._drawdown_from_peak_pct:
                                return True, f"drawdown_from_peak ({symbol}: {drawdown_pct:.1f}%)"
                    except (ValueError, TypeError):
                        pass

            # 5. Funding rate change — only trigger if rate changed significantly since last eval
            try:
                funding = sym_indicators.get("funding_rate")
                if funding is not None:
                    funding_f = float(funding)
                    last_funding = self._last_eval_funding.get(symbol)
                    if last_funding is not None:
                        funding_delta = abs(funding_f - last_funding)
                        if funding_delta >= self._funding_rate_threshold:
                            return True, f"funding_change ({symbol}: delta {funding_delta*100:.4f}%)"
                    elif abs(funding_f) >= self._funding_rate_threshold:
                        # No baseline yet — trigger on extreme absolute value
                        return True, f"funding_spike ({symbol}: {funding_f*100:.4f}%)"
            except (ValueError, TypeError):
                pass

            # 6. Volume anomaly (skip if same stale value from last eval)
            try:
                vol_last = sym_indicators.get("volume_last_candle", sym_indicators.get("volume_1m"))
                vol_avg = sym_indicators.get("volume_20_avg", sym_indicators.get("volume_avg"))
                if vol_last is not None and vol_avg is not None:
                    vol_last_f, vol_avg_f = float(vol_last), float(vol_avg)
                    last_vol = self._last_eval_volume.get(symbol)
                    if vol_avg_f > 0 and vol_last_f > self._volume_anomaly_multiplier * vol_avg_f:
                        if last_vol is None or vol_last_f != last_vol:
                            ratio = vol_last_f / vol_avg_f
                            return True, f"volume_anomaly ({symbol}: {ratio:.1f}x avg)"
            except (ValueError, TypeError):
                pass

        # 7. Regime change — compute current regime (with cooldown to avoid hot-path overhead)
        now = time.monotonic()
        if (
            self._last_regime is not None
            and indicators
            and (now - self._last_regime_check_time) >= self._REGIME_CHECK_COOLDOWN_S
        ):
            self._last_regime_check_time = now
            first_sym = next(iter(indicators), None)
            if first_sym:
                current_regime = _compute_regime_label(indicators[first_sym])
                if current_regime is not None and current_regime != self._last_regime:
                    return True, f"regime_change ({self._last_regime} → {current_regime})"

        return False, None

    def mark_triggered(self) -> None:
        """Record that a trigger just fired (for debounce)."""
        self._last_trigger_time = time.monotonic()

    def mark_evaluated(self, positions: List[Dict[str, Any]], regime: Optional[str] = None, indicators: Optional[Dict[str, Any]] = None) -> None:
        """Reset trigger state after an LLM evaluation completes."""
        self._last_eval_time = time.monotonic()
        self._last_regime = regime
        self._last_eval_prices.clear()
        self._last_eval_funding.clear()
        self._last_eval_volume.clear()

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue
            try:
                mark_price = float(pos.get("markPrice", pos.get("mark_price", 0)))
                if mark_price > 0:
                    self._last_eval_prices[symbol] = mark_price
            except (ValueError, TypeError):
                pass

        # Store funding rates and volume at evaluation time
        if indicators:
            for symbol, sym_ind in indicators.items():
                try:
                    funding = sym_ind.get("funding_rate")
                    if funding is not None:
                        self._last_eval_funding[symbol] = float(funding)
                except (ValueError, TypeError):
                    pass
                try:
                    vol = sym_ind.get("volume_last_candle", sym_ind.get("volume_1m"))
                    if vol is not None:
                        self._last_eval_volume[symbol] = float(vol)
                except (ValueError, TypeError):
                    pass

    def mark_initial_prices(self, positions: List[Dict[str, Any]], regime: Optional[str] = None) -> None:
        """Initialize baseline prices on cold start without resetting staleness timer."""
        self._last_regime = regime
        self._last_eval_prices.clear()

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue
            try:
                mark_price = float(pos.get("markPrice", pos.get("mark_price", 0)))
                if mark_price > 0:
                    self._last_eval_prices[symbol] = mark_price
            except (ValueError, TypeError):
                pass

    def check_all_triggers(
        self,
        positions: List[Dict[str, Any]],
        indicators: Optional[Dict[str, Any]] = None,
        peak_pnl: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[str, str, float]]:
        """Check all triggers for all positions without short-circuiting.

        Returns list of (symbol, reason, priority_score) sorted by priority descending.
        Higher priority = more urgent. Dedupes per symbol (keeps highest priority trigger).
        """
        indicators = indicators or {}
        peak_pnl = peak_pnl or {}
        results: Dict[str, Tuple[str, float]] = {}  # symbol -> (reason, priority)

        # Staleness is account-wide, not per-symbol
        elapsed = time.monotonic() - self._last_eval_time
        if elapsed >= self._staleness_alarm_s:
            # Return all position symbols with staleness reason
            for pos in positions:
                sym = pos.get("symbol", "")
                if sym:
                    results[sym] = (f"staleness_alarm ({int(elapsed)}s)", 1000.0)
            return sorted(
                [(sym, reason, prio) for sym, (reason, prio) in results.items()],
                key=lambda x: x[2], reverse=True,
            )

        # Debounce check
        now = time.monotonic()
        if (now - self._last_trigger_time) < self._min_trigger_interval_s:
            return []

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue

            # New position — register as trigger but continue checking for higher-priority signals
            if symbol not in self._last_eval_prices and self._last_eval_prices:
                self._update_result(results, symbol, f"new_position ({symbol})", 200.0)

            # Price move
            try:
                mark_price = float(pos.get("markPrice", pos.get("mark_price", 0)))
                if mark_price > 0 and symbol in self._last_eval_prices:
                    last_price = self._last_eval_prices[symbol]
                    if last_price > 0:
                        move_pct = abs(mark_price - last_price) / last_price * 100
                        if move_pct >= self._price_move_pct:
                            self._update_result(results, symbol, f"price_move ({symbol}: {move_pct:.2f}%)", move_pct)
            except (ValueError, TypeError):
                pass

            sym_indicators = indicators.get(symbol, {})

            # PnL velocity
            try:
                vel = sym_indicators.get("pnl_velocity_30s")
                if vel is not None and abs(float(vel)) >= self._pnl_velocity_pct / 100:
                    prio = abs(float(vel)) * 100
                    self._update_result(results, symbol, f"pnl_velocity ({symbol}: {float(vel)*100:.2f}%/30s)", prio)
            except (ValueError, TypeError):
                pass

            # Drawdown from peak
            if symbol in peak_pnl:
                peak = peak_pnl[symbol]
                if peak > 0:
                    try:
                        current = float(pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0)))
                        if current < peak:
                            drawdown_pct = (peak - current) / peak * 100
                            if drawdown_pct >= self._drawdown_from_peak_pct:
                                self._update_result(results, symbol, f"drawdown_from_peak ({symbol}: {drawdown_pct:.1f}%)", drawdown_pct)
                    except (ValueError, TypeError):
                        pass

            # Funding rate change
            try:
                funding = sym_indicators.get("funding_rate")
                if funding is not None:
                    funding_f = float(funding)
                    last_funding = self._last_eval_funding.get(symbol)
                    if last_funding is not None:
                        funding_delta = abs(funding_f - last_funding)
                        if funding_delta >= self._funding_rate_threshold:
                            self._update_result(results, symbol, f"funding_change ({symbol}: delta {funding_delta*100:.4f}%)", 50.0)
                    elif abs(funding_f) >= self._funding_rate_threshold:
                        self._update_result(results, symbol, f"funding_spike ({symbol}: {funding_f*100:.4f}%)", 50.0)
            except (ValueError, TypeError):
                pass

            # Volume anomaly
            try:
                vol_last = sym_indicators.get("volume_last_candle", sym_indicators.get("volume_1m"))
                vol_avg = sym_indicators.get("volume_20_avg", sym_indicators.get("volume_avg"))
                if vol_last is not None and vol_avg is not None:
                    vol_last_f, vol_avg_f = float(vol_last), float(vol_avg)
                    last_vol = self._last_eval_volume.get(symbol)
                    if vol_avg_f > 0 and vol_last_f > self._volume_anomaly_multiplier * vol_avg_f:
                        if last_vol is None or vol_last_f != last_vol:
                            ratio = vol_last_f / vol_avg_f
                            self._update_result(results, symbol, f"volume_anomaly ({symbol}: {ratio:.1f}x avg)", ratio * 10)
            except (ValueError, TypeError):
                pass

        # Regime change is account-wide — assign to the first position symbol
        now = time.monotonic()
        if (
            self._last_regime is not None
            and indicators
            and (now - self._last_regime_check_time) >= self._REGIME_CHECK_COOLDOWN_S
        ):
            self._last_regime_check_time = now
            first_sym = next(iter(indicators), None)
            if first_sym:
                current_regime = _compute_regime_label(indicators[first_sym])
                if current_regime is not None and current_regime != self._last_regime:
                    # Add regime change to all positions
                    for pos in positions:
                        sym = pos.get("symbol", "")
                        if sym and sym not in results:
                            self._update_result(results, sym, f"regime_change ({self._last_regime} -> {current_regime})", 60.0)

        return sorted(
            [(sym, reason, prio) for sym, (reason, prio) in results.items()],
            key=lambda x: x[2], reverse=True,
        )

    @staticmethod
    def _update_result(results: Dict[str, Tuple[str, float]], symbol: str, reason: str, priority: float) -> None:
        """Keep highest-priority trigger per symbol."""
        existing = results.get(symbol)
        if existing is None or priority > existing[1]:
            results[symbol] = (reason, priority)

    @property
    def seconds_since_last_eval(self) -> float:
        return time.monotonic() - self._last_eval_time
