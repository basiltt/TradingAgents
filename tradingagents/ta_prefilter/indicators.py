"""Extended technical indicators for the pre-filter engine.

All functions accept a pandas DataFrame with columns: open, high, low, close, volume.
They return Series or scalar values for scoring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3):
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(window=d_period).mean()
    return k, d


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, min_periods=period).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    mid = sma(close, period)
    std = close.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    width = (upper - lower) / mid
    return upper, mid, lower, width


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff())
    return (volume * direction).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0):
    atr_val = atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper_band = (hl2 + multiplier * atr_val).values
    lower_band = (hl2 - multiplier * atr_val).values
    close_arr = close.values
    n = len(close_arr)

    st_dir = np.ones(n, dtype=np.int8)
    st = np.full(n, np.nan)

    for i in range(1, n):
        if close_arr[i] > upper_band[i - 1]:
            st_dir[i] = 1
        elif close_arr[i] < lower_band[i - 1]:
            st_dir[i] = -1
        else:
            st_dir[i] = st_dir[i - 1]

        st[i] = lower_band[i] if st_dir[i] == 1 else upper_band[i]

    return pd.Series(st, index=close.index), pd.Series(st_dir, index=close.index)


def detect_structure(high: pd.Series, low: pd.Series, lookback: int = 20) -> dict:
    """Detect market structure: higher highs/lows or lower highs/lows.

    Uses percentile-based comparison (25th/75th) rather than min/max to avoid
    single-candle spike distortion.
    """
    if len(high) < lookback * 2:
        return {"trend": "unknown", "higher_high": False, "higher_low": False, "lower_high": False, "lower_low": False}

    recent_highs = high.iloc[-lookback:]
    prior_highs = high.iloc[-lookback * 2:-lookback]
    recent_lows = low.iloc[-lookback:]
    prior_lows = low.iloc[-lookback * 2:-lookback]

    # Use 75th percentile for highs and 25th for lows — more robust than min/max
    hh = float(recent_highs.quantile(0.75)) > float(prior_highs.quantile(0.75))
    hl = float(recent_lows.quantile(0.25)) > float(prior_lows.quantile(0.25))
    lh = float(recent_highs.quantile(0.75)) < float(prior_highs.quantile(0.75))
    ll = float(recent_lows.quantile(0.25)) < float(prior_lows.quantile(0.25))

    if hh and hl:
        trend = "bullish"
    elif lh and ll:
        trend = "bearish"
    else:
        trend = "ranging"

    return {"trend": trend, "higher_high": hh, "higher_low": hl, "lower_high": lh, "lower_low": ll}


def volume_profile_signal(close: pd.Series, volume: pd.Series, bins: int = 20) -> dict:
    """Simple volume profile: find high-volume nodes relative to current price."""
    if len(close) < bins:
        return {"position": "unknown", "poc_distance_pct": 0.0}

    total_volume = volume.sum()
    if total_volume == 0:
        return {"position": "at_poc", "poc_distance_pct": 0.0}

    price_range = np.linspace(close.min(), close.max(), bins + 1)
    vol_at_price = np.zeros(bins)

    for i in range(bins):
        if i == bins - 1:
            mask = (close >= price_range[i]) & (close <= price_range[i + 1])
        else:
            mask = (close >= price_range[i]) & (close < price_range[i + 1])
        vol_at_price[i] = volume[mask].sum()

    poc_idx = np.argmax(vol_at_price)
    poc_price = (price_range[poc_idx] + price_range[poc_idx + 1]) / 2
    current = close.iloc[-1]
    distance_pct = (current - poc_price) / poc_price * 100

    if current > poc_price:
        position = "above_poc"
    elif current < poc_price:
        position = "below_poc"
    else:
        position = "at_poc"

    return {"position": position, "poc_distance_pct": distance_pct}
