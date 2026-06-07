"""Market-scoped regime classification + per-symbol EMA mean (Phase 1, market_data.py).

Pure indicator math over kline dicts (shape from KlineCacheService.get_klines:
{"open","high","low","close","volume", "open_time"}). Market-scoped (BTC) and
deliberately simpler than the per-symbol ai_manager_regime classifier (ADR-2).

Classifier (SD1): from BTC klines compute
  atr_ratio       = ATR(n) / SMA(ATR(n) over n)          # needs >= 2n+1 candles
  ema_distance_pct = (close - EMA(n)) / EMA(n) * 100
and first-match:
  unknown   if candles < required depth (2n+1)
  volatile  if atr_ratio >= regime_volatile_atr (default 2.0)
  trending  if abs(ema_distance_pct) >= regime_trend_ema_dist_pct (default 1.0)
  ranging   otherwise
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services.scan_context import BtcRegime

Kline = dict[str, Any]


def _closes(klines: list[Kline]) -> list[float]:
    return [float(k["close"]) for k in klines]


def _true_ranges(klines: list[Kline]) -> list[float]:
    """Wilder's true range series (length len(klines)-1)."""
    trs: list[float] = []
    for i in range(1, len(klines)):
        high = float(klines[i]["high"])
        low = float(klines[i]["low"])
        prev_close = float(klines[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return trs


def _wilder_atr(trs: list[float], n: int) -> list[float]:
    """Wilder-smoothed ATR series from a true-range series. Returns one ATR value
    per position from index n-1 onward (length len(trs)-n+1)."""
    if len(trs) < n:
        return []
    atrs: list[float] = []
    atr = sum(trs[:n]) / n  # initial ATR = simple average of first n TRs
    atrs.append(atr)
    for i in range(n, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        atrs.append(atr)
    return atrs


def ema(values: list[float], period: int) -> Optional[float]:
    """Final EMA value over `values` with the given period, or None if too short."""
    if len(values) < period or period < 1:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period  # seed with SMA of first `period`
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def compute_ema_mean(klines: list[Kline], period: int) -> Optional[float]:
    """EMA of closes over `period`. None if fewer than `period` candles (F2 mean)."""
    closes = _closes(klines)
    return ema(closes, period)


def compute_ema_distance_pct(klines: list[Kline], period: int) -> Optional[float]:
    """(last_close - EMA(period)) / EMA(period) * 100. None if too short."""
    closes = _closes(klines)
    e = ema(closes, period)
    if e is None or e == 0:
        return None
    return (closes[-1] - e) / e * 100.0


def required_depth(lookback: int) -> int:
    """Minimum candles for a non-degenerate atr_ratio: an n-wide SMA over the ATR
    series needs ~2n TR values (+1 for the first TR's prev-close). (SD1a)"""
    return 2 * lookback + 1


def compute_atr_ratio(klines: list[Kline], n: int) -> Optional[float]:
    """ATR(n) / SMA(ATR(n) over n). None if fewer than required_depth(n) candles
    (prevents the degenerate atr_ratio == 1.0 from a single ATR value).

    A genuinely flat/calm market (every ATR == 0) is NOT "unavailable" — it has a
    well-defined neutral ratio of 1.0 (current volatility == its own average). We
    only return None when there is insufficient *history*, never for low volatility.
    """
    if len(klines) < required_depth(n):
        return None
    trs = _true_ranges(klines)
    atrs = _wilder_atr(trs, n)
    if len(atrs) < n:
        return None
    sma_atr = sum(atrs[-n:]) / n
    if sma_atr == 0:
        # Flat market: latest ATR is also 0 => ratio is 1.0 (neutral), not undefined.
        return 1.0
    return atrs[-1] / sma_atr


def classify_regime(
    klines: list[Kline],
    *,
    lookback: int,
    volatile_atr: float = 2.0,
    trend_ema_dist_pct: float = 1.0,
) -> BtcRegime:
    """Classify the market (BTC) regime. First-match rules (SD1)."""
    if len(klines) < required_depth(lookback):
        return {"regime": "unknown", "vol_value": None, "unavailable": True}

    atr_ratio = compute_atr_ratio(klines, lookback)
    ema_dist = compute_ema_distance_pct(klines, lookback)
    if atr_ratio is None or ema_dist is None:
        return {"regime": "unknown", "vol_value": atr_ratio, "unavailable": True}

    if atr_ratio >= volatile_atr:
        regime = "volatile"
    elif abs(ema_dist) >= trend_ema_dist_pct:
        regime = "trending"
    else:
        regime = "ranging"
    return {"regime": regime, "vol_value": atr_ratio, "unavailable": False}
