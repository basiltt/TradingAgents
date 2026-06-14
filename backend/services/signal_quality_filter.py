"""Signal-quality filters for trade selection (FIX-005).

Pure, deterministic functions that decide whether a generated signal should be
TRADED — separate from signal generation. Backtested across two held-out samples
(signal_research/): applying these lifts win-rate ~60.7%->67.4% and directional
accuracy ~57.6%->63.3%, generalizing across both samples (unlike LLM-prompt changes,
which overfit). Because they are deterministic, the same signal always yields the same
decision (100% reproducible).

Three filters (all proven to generalize):
  1. trend_alignment: a SHORT needs 1h AND 4h downtrend; a LONG needs 1h AND 4h uptrend.
     Counter-trend trades won ~39% vs ~56% trend-aligned in backtest.
  2. falling_knife_short: do not SHORT a coin that already crashed (24h <= -15%) and is
     oversold (RSI14 < 32) / sitting on recent support. These won ~36% (the ESPORTS trap).
  3. (score gating stays in auto_trade_service via the existing min_score knob.)

Inputs are plain kline dicts/objects exposing high/low/close (h/l/c or .high/.low/.close).
All functions FAIL OPEN (return "allowed" / None) on insufficient data — a filter must
never block a trade just because indicators couldn't be computed.
"""
from __future__ import annotations
from typing import Any, Optional

# --- kline accessors (tolerant of dict {o,h,l,c} or {open,high,low,close} or objects) ---
def _c(k: Any) -> Optional[float]:
    for attr in ("c", "close"):
        if isinstance(k, dict) and attr in k:
            return float(k[attr])
        if hasattr(k, attr):
            return float(getattr(k, attr))
    return None

def _h(k: Any) -> Optional[float]:
    for attr in ("h", "high"):
        if isinstance(k, dict) and attr in k:
            return float(k[attr])
        if hasattr(k, attr):
            return float(getattr(k, attr))
    return None

def _l(k: Any) -> Optional[float]:
    for attr in ("l", "low"):
        if isinstance(k, dict) and attr in k:
            return float(k[attr])
        if hasattr(k, attr):
            return float(getattr(k, attr))
    return None

def _ema(vals: list[float], n: int) -> Optional[float]:
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e

def _rsi(closes: list[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    g = l = 0.0
    for i in range(-n, 0):
        ch = closes[i] - closes[i - 1]
        g += max(ch, 0); l += max(-ch, 0)
    if l == 0:
        return 100.0
    return 100 - 100 / (1 + (g / n) / (l / n))

def trend_direction(klines: list[Any], fast: int = 9, slow: int = 21) -> Optional[str]:
    """'up'/'down' from EMA(fast) vs EMA(slow) on the given klines, or None if insufficient.
    klines must be ASC by time."""
    closes = [c for c in (_c(k) for k in klines) if c is not None]
    ef, es = _ema(closes, fast), _ema(closes, slow)
    if ef is None or es is None:
        return None
    return "up" if ef > es else "down"

def _norm_dir(direction: str) -> Optional[str]:
    d = (direction or "").lower()
    if d in ("buy", "long"):
        return "buy"
    if d in ("sell", "short"):
        return "sell"
    return None

def trend_aligned(direction: str, kl_1h: list[Any], kl_4h: list[Any]) -> Optional[bool]:
    """True if the trade follows the 1h AND 4h trend; False if counter-trend.
    Returns None (fail-open: caller should ALLOW) if either trend can't be computed."""
    d = _norm_dir(direction)
    if d is None:
        return None
    t1 = trend_direction(kl_1h)
    t4 = trend_direction(kl_4h)
    if t1 is None or t4 is None:
        return None
    want = "up" if d == "buy" else "down"
    return t1 == want and t4 == want

def is_falling_knife_short(direction: str, kl_5m: list[Any],
                           crash_pct: float = -15.0, rsi_oversold: float = 32.0,
                           support_dist_pct: float = 1.5) -> bool:
    """True if this is a SHORT into a likely dead-cat bounce: the coin already crashed
    >= crash_pct over ~24h AND (oversold OR sitting within support_dist_pct of the
    recent swing low). Only applies to shorts. Fail-open: False on insufficient data.
    kl_5m must be ASC by time; ~288 candles = 24h."""
    if _norm_dir(direction) != "sell":
        return False
    closes = [c for c in (_c(k) for k in kl_5m) if c is not None]
    if len(closes) < 50:
        return False
    cur = closes[-1]
    # 24h return (288 5m candles); fall back to oldest available
    ref = closes[-288] if len(closes) >= 288 else closes[0]
    ret_24h = (cur - ref) / ref * 100 if ref else 0.0
    if ret_24h > crash_pct:   # did NOT crash enough -> not a knife
        return False
    rsi = _rsi(closes, 14) or 50.0
    lows = [x for x in (_l(k) for k in kl_5m[-48:]) if x is not None]
    swing_low = min(lows) if lows else cur
    dist_to_low = (cur - swing_low) / cur * 100 if cur else 99.0
    return (rsi < rsi_oversold) or (dist_to_low < support_dist_pct)
