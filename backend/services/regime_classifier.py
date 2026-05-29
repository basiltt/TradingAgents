"""Regime Classifier Service.

Provides indicator computation, rule-based regime classification, and optional
LLM confirmation.  Results are persisted to the ``regime_snapshots`` table.
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _ema(values: list[float], period: int) -> float:
    """Return the final EMA value for *values* using *period*."""
    if not values:
        raise ValueError("values must not be empty")
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _sma(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


# ---------------------------------------------------------------------------
# Public pure functions
# ---------------------------------------------------------------------------


def classify_from_indicators(
    adx: float,
    price: float,
    ema20: float,
    atr_pct: float,
    atr_avg_30: float,
    bb_width: float,
    bb_width_median: float,
) -> str:
    """Classify market regime from pre-computed indicators.

    Priority order: volatile > trending > ranging.

    Args:
        adx: Average Directional Index (14-period).
        price: Current close price.
        ema20: 20-period EMA of close prices.
        atr_pct: ATR expressed as a percentage of current price.
        atr_avg_30: 30-period average of rolling ATR%.
        bb_width: Current Bollinger-Band width percentage.
        bb_width_median: Historical median of Bollinger-Band width.

    Returns:
        One of "volatile", "trending_up", "trending_down", or "ranging".
    """
    if atr_pct > 1.5 * atr_avg_30:
        return "volatile"
    if adx > 25 and price > ema20:
        return "trending_up"
    if adx > 25 and price < ema20:
        return "trending_down"
    if adx < 20 and bb_width < bb_width_median:
        return "ranging"
    return "ranging"


def compute_indicators(candles: list[dict]) -> dict:
    """Compute regime-relevant indicators from a list of OHLC candles.

    Args:
        candles: List of dicts with keys ``open``, ``high``, ``low``, ``close``
            (all floats).  Must contain at least 30 entries.

    Returns:
        Dict with keys: ``adx``, ``atr_pct``, ``atr_avg_30``, ``ema20``,
        ``price``, ``bb_width``, ``bb_width_median``.

    Raises:
        ValueError: If fewer than 30 candles are supplied.
    """
    if len(candles) < 30:
        raise ValueError(f"Need at least 30 candles, got {len(candles)}")

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    if not closes[-1]:
        raise ValueError("Last candle close price is 0 or None")

    price = closes[-1]

    # --- EMA(20) ---
    ema20 = _ema(closes, 20)

    # --- True Range series ---
    tr_series: list[float] = []
    for i in range(1, len(candles)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_series.append(tr)

    # --- ATR(14) — simple moving average of last 14 TRs ---
    atr14 = _sma(tr_series[-14:]) if len(tr_series) >= 14 else _sma(tr_series)

    # --- atr_pct (current) ---
    atr_pct = (atr14 / price) * 100.0 if price else 0.0

    # --- atr_avg_30: average of rolling ATR% over last 30 bars ---
    # Build a rolling ATR% series (one value per bar using a 14-bar window).
    rolling_atr_pct: list[float] = []
    for i in range(len(tr_series)):
        start = max(0, i - 13)
        window = tr_series[start : i + 1]
        bar_atr = _sma(window)
        bar_close = closes[i + 1]  # tr_series[i] corresponds to candles[i+1]
        rolling_atr_pct.append((bar_atr / bar_close) * 100.0 if bar_close else 0.0)
    atr_avg_30 = _sma(rolling_atr_pct[-30:]) if len(rolling_atr_pct) >= 30 else _sma(rolling_atr_pct)

    # --- Bollinger Bands (20-period) ---
    def _bb_width_at(close_slice: list[float]) -> float:
        window = close_slice[-20:] if len(close_slice) >= 20 else close_slice
        sma = _sma(window)
        sd = _std(window)
        upper = sma + 2 * sd
        lower = sma - 2 * sd
        return ((upper - lower) / sma) * 100.0 if sma else 0.0

    bb_width = _bb_width_at(closes)

    # Build a history of BB widths for median computation.
    bb_widths: list[float] = []
    for i in range(20, len(closes) + 1):
        bb_widths.append(_bb_width_at(closes[:i]))
    bb_width_median = statistics.median(bb_widths) if bb_widths else bb_width

    # --- ADX(14) simplified ---
    adx = _compute_adx(highs, lows, closes, period=14)

    return {
        "adx": adx,
        "atr_pct": atr_pct,
        "atr_avg_30": atr_avg_30,
        "ema20": ema20,
        "price": price,
        "bb_width": bb_width,
        "bb_width_median": bb_width_median,
    }


def _compute_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Simplified Wilder-smoothed ADX."""
    if len(highs) < period + 1:
        return 0.0

    plus_dm_series: list[float] = []
    minus_dm_series: list[float] = []
    tr_series: list[float] = []

    for i in range(1, len(highs)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        plus_dm_series.append(plus_dm)
        minus_dm_series.append(minus_dm)
        tr_series.append(tr)

    # Wilder smoothing: seed with sum of first `period` values, then roll.
    def _wilder_smooth(series: list[float], p: int) -> list[float]:
        if len(series) < p:
            return [sum(series)]
        smoothed = [sum(series[:p])]
        for v in series[p:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / p + v)
        return smoothed

    smooth_tr = _wilder_smooth(tr_series, period)
    smooth_plus = _wilder_smooth(plus_dm_series, period)
    smooth_minus = _wilder_smooth(minus_dm_series, period)

    dx_series: list[float] = []
    for s_tr, s_plus, s_minus in zip(smooth_tr, smooth_plus, smooth_minus):
        if s_tr == 0:
            continue
        plus_di = 100.0 * s_plus / s_tr
        minus_di = 100.0 * s_minus / s_tr
        denom = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / denom if denom else 0.0
        dx_series.append(dx)

    if not dx_series:
        return 0.0

    # Final ADX = Wilder-smoothed DX series (take last value).
    adx_series = _wilder_smooth(dx_series, period)
    return adx_series[-1] / period  # normalise to same scale as seed sum


# ---------------------------------------------------------------------------
# RegimeClassifier class
# ---------------------------------------------------------------------------


class RegimeClassifier:
    """Classifies market regime for one or more symbols and persists results.

    Args:
        db: Database wrapper with a ``pool`` attribute (asyncpg pool).
        llm_callable: Optional async callable ``(prompt: str) -> dict`` that
            returns ``{"regime": str, "confidence": float}``.
    """

    def __init__(self, db: Any, llm_callable: Optional[Callable] = None) -> None:
        self._db = db
        self._llm = llm_callable

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def classify_symbol(self, symbol: str, candles: list[dict]) -> dict:
        """Classify regime for *symbol* given its recent *candles*.

        Args:
            symbol: Trading pair symbol, e.g. ``"BTCUSDT"``.
            candles: List of OHLC dicts (``open``, ``high``, ``low``, ``close``).

        Returns:
            Dict with keys ``regime``, ``indicators``, ``llm_confirmed``,
            ``llm_regime``.
        """
        indicators = compute_indicators(candles)

        indicator_regime = classify_from_indicators(
            adx=indicators["adx"],
            price=indicators["price"],
            ema20=indicators["ema20"],
            atr_pct=indicators["atr_pct"],
            atr_avg_30=indicators["atr_avg_30"],
            bb_width=indicators["bb_width"],
            bb_width_median=indicators["bb_width_median"],
        )

        llm_confirmed = False
        llm_regime: Optional[str] = None
        final_regime = indicator_regime

        if self._llm is not None:
            prompt = self._build_llm_prompt(symbol, indicators, candles[-6:])
            try:
                llm_result = await self._llm(prompt)
                llm_regime = llm_result.get("regime")
                confidence = float(llm_result.get("confidence", 0.0))
                if confidence > 0.7 and llm_regime:
                    final_regime = llm_regime
                    llm_confirmed = True
            except Exception:
                logger.exception("LLM callable failed for symbol %s", symbol)

        await self._persist(
            symbol=symbol,
            regime=final_regime,
            indicators=indicators,
            llm_confirmed=llm_confirmed,
            llm_regime=llm_regime,
        )

        return {
            "regime": final_regime,
            "indicators": indicators,
            "llm_confirmed": llm_confirmed,
            "llm_regime": llm_regime,
        }

    async def run_all(
        self,
        symbols: list[str],
        fetch_candles_fn: Callable,
    ) -> list[dict]:
        """Classify regime for all *symbols* in sequence.

        Args:
            symbols: List of trading pair symbols.
            fetch_candles_fn: Async callable
                ``(symbol, interval, limit) -> list[dict]``.

        Returns:
            List of classification result dicts (one per successfully
            processed symbol).
        """
        results: list[dict] = []
        for symbol in symbols:
            try:
                candles = await fetch_candles_fn(symbol, interval="240", limit=50)
                result = await self.classify_symbol(symbol, candles)
                results.append(result)
            except Exception:
                logger.exception("Failed to classify regime for symbol %s", symbol)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_llm_prompt(
        self,
        symbol: str,
        indicators: dict,
        recent_candles: list[dict],
    ) -> str:
        candle_lines = "\n".join(
            f"  open={c['open']:.4f} high={c['high']:.4f} "
            f"low={c['low']:.4f} close={c['close']:.4f}"
            for c in recent_candles
        )
        return (
            f"Classify the market regime for {symbol}.\n\n"
            f"Indicators:\n"
            f"  ADX={indicators['adx']:.2f}\n"
            f"  Price={indicators['price']:.4f}\n"
            f"  EMA20={indicators['ema20']:.4f}\n"
            f"  ATR%={indicators['atr_pct']:.4f}\n"
            f"  ATR_avg30%={indicators['atr_avg_30']:.4f}\n"
            f"  BB_width={indicators['bb_width']:.4f}\n"
            f"  BB_width_median={indicators['bb_width_median']:.4f}\n\n"
            f"Last 6 candles (most recent last):\n{candle_lines}\n\n"
            "Respond with JSON: "
            '{"regime": "<trending_up|trending_down|ranging|volatile>", "confidence": <0.0-1.0>}'
        )

    async def _persist(
        self,
        symbol: str,
        regime: str,
        indicators: dict,
        llm_confirmed: bool,
        llm_regime: Optional[str],
    ) -> None:
        query = """
            INSERT INTO regime_snapshots
                (symbol, regime, adx, atr_pct, bb_width_pct, llm_confirmed, llm_regime)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        await self._db.pool.execute(
            query,
            symbol,
            regime,
            indicators["adx"],
            indicators["atr_pct"],
            indicators["bb_width"],
            llm_confirmed,
            llm_regime,
        )
