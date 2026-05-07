"""TA Pre-Filter Engine — orchestrates data fetching and scoring.

Usage:
    engine = TAPreFilterEngine(symbol="BTCUSDT", interval="D")
    result = engine.run()
    if result.should_proceed:
        # run full LLM analysis
    else:
        # skip — result.reason explains why
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from tradingagents.ta_prefilter import indicators as ind
from tradingagents.ta_prefilter.scorer import ScoreBreakdown, compute_composite_score

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 40


@dataclass
class PreFilterResult:
    score: float
    threshold: float
    should_proceed: bool
    breakdown: ScoreBreakdown
    reason: str
    duration_ms: float
    raw_signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "threshold": self.threshold,
            "should_proceed": self.should_proceed,
            "breakdown": self.breakdown.to_dict(),
            "reason": self.reason,
            "duration_ms": round(self.duration_ms, 1),
        }


class TAPreFilterEngine:
    """Runs comprehensive TA on a crypto symbol and produces an opportunity score."""

    def __init__(
        self,
        symbol: str,
        interval: str = "D",
        threshold: float = DEFAULT_THRESHOLD,
        cache: dict | None = None,
        limiter: Any = None,
        circuit_breaker: Any = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        self.symbol = symbol
        self.interval = interval
        self.threshold = threshold
        self.cache = cache
        self.limiter = limiter
        self.circuit_breaker = circuit_breaker
        self.api_key = api_key
        self.api_secret = api_secret

    def run(self) -> PreFilterResult:
        start = time.monotonic()
        try:
            from concurrent.futures import ThreadPoolExecutor
            from tradingagents.dataflows.bybit_data import normalize_bybit_symbol

            # Validate symbol once upfront to fail fast
            self._normalized_symbol = normalize_bybit_symbol(self.symbol)

            with ThreadPoolExecutor(max_workers=2) as executor:
                kline_future = executor.submit(self._fetch_klines)
                deriv_future = executor.submit(self._analyze_derivatives)

                df = kline_future.result()
                derivatives_inputs = deriv_future.result()

            if df is None or len(df) < 50:
                return self._insufficient_data(start)

            trend_inputs = self._analyze_trend(df)
            momentum_inputs = self._analyze_momentum(df)
            volatility_inputs = self._analyze_volatility(df)
            volume_inputs = self._analyze_volume(df)

            breakdown = compute_composite_score(
                trend_inputs, momentum_inputs, volatility_inputs,
                volume_inputs, derivatives_inputs,
            )

            should_proceed = breakdown.total >= self.threshold
            if should_proceed:
                reason = f"TA score {breakdown.total:.0f}/{100} >= threshold {self.threshold:.0f} — proceeding with LLM analysis"
            else:
                reason = f"TA score {breakdown.total:.0f}/{100} < threshold {self.threshold:.0f} — skipping LLM analysis (no clear opportunity)"

            duration_ms = (time.monotonic() - start) * 1000
            return PreFilterResult(
                score=breakdown.total,
                threshold=self.threshold,
                should_proceed=should_proceed,
                breakdown=breakdown,
                reason=reason,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            logger.warning("TA pre-filter failed for %s, defaulting to proceed: %s", self.symbol, exc)
            duration_ms = (time.monotonic() - start) * 1000
            return PreFilterResult(
                score=100,
                threshold=self.threshold,
                should_proceed=True,
                breakdown=ScoreBreakdown(25, 25, 20, 15, 15),
                reason=f"Pre-filter error ({type(exc).__name__}), defaulting to proceed",
                duration_ms=duration_ms,
            )

    def _insufficient_data(self, start: float) -> PreFilterResult:
        duration_ms = (time.monotonic() - start) * 1000
        return PreFilterResult(
            score=100,
            threshold=self.threshold,
            should_proceed=True,
            breakdown=ScoreBreakdown(25, 25, 20, 15, 15),
            reason="Insufficient data for TA pre-filter, defaulting to proceed",
            duration_ms=duration_ms,
        )

    def _fetch_klines(self) -> Optional[pd.DataFrame]:
        from tradingagents.dataflows.bybit_data import get_bybit_klines

        symbol = self._normalized_symbol
        now_ms = int(time.time() * 1000)

        interval_ms_map = {"15": 15 * 60_000, "60": 3_600_000, "240": 14_400_000, "D": 86_400_000}
        candle_ms = interval_ms_map.get(self.interval, 86_400_000)
        # Fetch 200 candles for robust indicator calculation
        start_time = now_ms - (200 * candle_ms)

        try:
            csv = get_bybit_klines(
                symbol, self.interval, start_time, now_ms,
                cache=self.cache, limiter=self.limiter, circuit_breaker=self.circuit_breaker,
                api_key=self.api_key, api_secret=self.api_secret,
            )
            df = pd.read_csv(io.StringIO(csv))
            df.columns = [c.lower().strip() for c in df.columns]
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            return df
        except Exception as exc:
            logger.warning("Failed to fetch klines for pre-filter: %s", exc)
            return None

    def _analyze_trend(self, df: pd.DataFrame) -> dict:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        ema_9 = ind.ema(close, 9)
        ema_21 = ind.ema(close, 21)
        ema_cross_bullish = bool(ema_9.iloc[-1] > ema_21.iloc[-1] and ema_9.iloc[-2] <= ema_21.iloc[-2])
        ema_cross_bearish = bool(ema_9.iloc[-1] < ema_21.iloc[-1] and ema_9.iloc[-2] >= ema_21.iloc[-2])

        adx_val = ind.adx(high, low, close)
        adx_current = float(adx_val.iloc[-1]) if not pd.isna(adx_val.iloc[-1]) else 0.0

        _, st_dir = ind.supertrend(high, low, close)
        st_current = int(st_dir.iloc[-1]) if not pd.isna(st_dir.iloc[-1]) else 0

        structure = ind.detect_structure(high, low)

        return {
            "adx_value": adx_current,
            "ema_cross_bullish": ema_cross_bullish,
            "ema_cross_bearish": ema_cross_bearish,
            "supertrend_direction": st_current,
            "structure_trend": structure["trend"],
        }

    def _analyze_momentum(self, df: pd.DataFrame) -> dict:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        rsi_val = ind.rsi(close)
        rsi_current = float(rsi_val.iloc[-1]) if not pd.isna(rsi_val.iloc[-1]) else 50.0

        macd_line, signal_line, histogram = ind.macd(close)
        macd_hist = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0.0
        # MACD cross in last 3 bars (sign must flip between positive and negative)
        macd_cross_recent = False
        if len(histogram) >= 3:
            signs = [np.sign(histogram.iloc[i]) for i in range(-3, 0)]
            if not any(np.isnan(s) for s in signs):
                # Only count as cross if we went from positive to negative or vice versa
                # (ignore zero — it means the histogram hasn't committed to a direction)
                first_nonzero = next((s for s in signs if s != 0), 0)
                last_nonzero = next((s for s in reversed(signs) if s != 0), 0)
                macd_cross_recent = (first_nonzero != 0 and last_nonzero != 0
                                     and first_nonzero != last_nonzero)

        # Histogram expanding (absolute value growing over last 2 bars)
        macd_histogram_growing = False
        if len(histogram) >= 2:
            prev_hist = histogram.iloc[-2]
            curr_hist = histogram.iloc[-1]
            if not pd.isna(prev_hist) and not pd.isna(curr_hist):
                macd_histogram_growing = abs(curr_hist) > abs(prev_hist)

        stoch_k, stoch_d = ind.stochastic(high, low, close)
        k_val = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50.0
        d_val = float(stoch_d.iloc[-1]) if not pd.isna(stoch_d.iloc[-1]) else 50.0

        return {
            "rsi_value": rsi_current,
            "macd_histogram": macd_hist,
            "macd_cross_recent": macd_cross_recent,
            "macd_histogram_growing": macd_histogram_growing,
            "stoch_k": k_val,
            "stoch_d": d_val,
        }

    def _analyze_volatility(self, df: pd.DataFrame) -> dict:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        upper, mid, lower, width = ind.bollinger_bands(close)
        current_width = float(width.iloc[-1]) if not pd.isna(width.iloc[-1]) else 0.0

        # Width percentile over lookback
        valid_widths = width.dropna()
        if len(valid_widths) > 10 and current_width > 0:
            percentile = float((valid_widths < current_width).sum() / len(valid_widths) * 100)
        else:
            percentile = 50.0

        # Price position relative to bands
        current_close = close.iloc[-1]
        bb_upper = upper.iloc[-1]
        bb_lower = lower.iloc[-1]
        bb_range = bb_upper - bb_lower if bb_upper != bb_lower else 1.0

        if current_close > bb_upper:
            price_vs_bb = "above_upper"
        elif current_close < bb_lower:
            price_vs_bb = "below_lower"
        elif (current_close - bb_lower) / bb_range > 0.85:
            price_vs_bb = "near_upper"
        elif (current_close - bb_lower) / bb_range < 0.15:
            price_vs_bb = "near_lower"
        else:
            price_vs_bb = "middle"

        atr_val = ind.atr(high, low, close)
        atr_current = float(atr_val.iloc[-1]) if not pd.isna(atr_val.iloc[-1]) else 0.0
        atr_pct = (atr_current / current_close * 100) if current_close > 0 else 0.0

        return {
            "bb_width": current_width,
            "bb_width_percentile": percentile,
            "atr_pct": atr_pct,
            "price_vs_bb": price_vs_bb,
        }

    def _analyze_volume(self, df: pd.DataFrame) -> dict:
        close = df["close"]
        volume = df["volume"]

        # OBV trend
        obv_val = ind.obv(close, volume)
        obv_ema = ind.ema(obv_val, 20)
        if len(obv_val) >= 2 and len(obv_ema) >= 2:
            if obv_val.iloc[-1] > obv_ema.iloc[-1]:
                obv_trend = "bullish"
            else:
                obv_trend = "bearish"
        else:
            obv_trend = "neutral"

        # Volume spike (last bar vs 20-period avg)
        vol_avg = volume.rolling(20).mean()
        volume_spike = bool(
            not pd.isna(vol_avg.iloc[-1])
            and vol_avg.iloc[-1] > 0
            and volume.iloc[-1] > 2 * vol_avg.iloc[-1]
        )

        vp = ind.volume_profile_signal(close, volume)

        return {
            "obv_trend": obv_trend,
            "volume_spike": volume_spike,
            "vp_position": vp["position"],
            "vp_distance_pct": vp["poc_distance_pct"],
        }

    def _analyze_derivatives(self) -> dict:
        """Fetch funding rate and OI data for derivatives scoring."""
        from tradingagents.dataflows.bybit_data import (
            get_bybit_funding_rates,
            get_bybit_open_interest,
        )

        funding_rate: float | None = None
        oi_change_pct: float | None = None

        try:
            symbol = self._normalized_symbol
            now_ms = int(time.time() * 1000)
            day_ago = now_ms - 86_400_000

            # Latest funding rate
            try:
                funding_str = get_bybit_funding_rates(
                    symbol, day_ago, now_ms,
                    cache=self.cache, limiter=self.limiter, circuit_breaker=self.circuit_breaker,
                    api_key=self.api_key, api_secret=self.api_secret,
                )
                for line in funding_str.strip().split("\n"):
                    if "Rate:" in line:
                        try:
                            rate_str = line.split("Rate:")[-1].strip()
                            funding_rate = float(rate_str)
                            break
                        except (ValueError, IndexError):
                            pass
            except Exception as exc:
                logger.debug("Funding rate unavailable for pre-filter: %s", exc)

            # OI change
            try:
                two_days_ago = now_ms - 2 * 86_400_000
                oi_str = get_bybit_open_interest(
                    symbol, "1h", two_days_ago, now_ms,
                    cache=self.cache, limiter=self.limiter, circuit_breaker=self.circuit_breaker,
                    api_key=self.api_key, api_secret=self.api_secret,
                )
                oi_values = []
                for line in oi_str.strip().split("\n"):
                    if "OI:" in line:
                        try:
                            oi_val = float(line.split("OI:")[-1].strip())
                            oi_values.append(oi_val)
                        except (ValueError, IndexError):
                            pass
                if len(oi_values) >= 2:
                    oldest = oi_values[-1]  # Bybit returns newest first
                    newest = oi_values[0]
                    if oldest > 0:
                        oi_change_pct = (newest - oldest) / oldest * 100
            except Exception as exc:
                logger.debug("OI data unavailable for pre-filter: %s", exc)

        except Exception as exc:
            logger.debug("Derivatives data unavailable for pre-filter: %s", exc)

        return {"funding_rate": funding_rate, "oi_change_pct": oi_change_pct}
