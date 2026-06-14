"""Phase 2: point-in-time FEATURE reconstruction (no lookahead).

Computes a rich technical snapshot from klines strictly before the anchor. This is
the data the LLM sees. Designed to be extended with new indicators as we iterate —
especially the reversal/bounce-risk features the ESPORTS failure showed were missing.

All features use only `before` klines (open_time < anchor). Multi-timeframe is built
by resampling 5m -> 15m/1h/4h locally (we only reliably have 5m in cache).
"""
from __future__ import annotations
import math

def ema(vals, n):
    if len(vals) < n: return None
    k = 2 / (n + 1); e = sum(vals[:n]) / n
    for v in vals[n:]: e = v * k + e * (1 - k)
    return e

def sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None

def rsi(closes, n=14):
    if len(closes) < n + 1: return None
    g = l = 0.0
    for i in range(-n, 0):
        ch = closes[i] - closes[i - 1]; g += max(ch, 0); l += max(-ch, 0)
    if l == 0: return 100.0
    return 100 - 100 / (1 + (g / n) / (l / n))

def atr(klines, n=14):
    if len(klines) < n + 1: return None
    trs = []
    for i in range(-n, 0):
        h, l, pc = klines[i]["h"], klines[i]["l"], klines[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n

def macd(closes):
    if len(closes) < 26: return None, None
    e12, e26 = ema(closes, 12), ema(closes, 26)
    if e12 is None or e26 is None: return None, None
    line = e12 - e26
    # signal ~ ema9 of macd line (approx with last values)
    return line, None

def resample(klines, factor):
    """Aggregate 5m klines into higher TF (factor=3 ->15m, 12 ->1h, 48 ->4h)."""
    out = []
    for i in range(0, len(klines) - factor + 1, factor):
        chunk = klines[i:i + factor]
        out.append({
            "open_time": chunk[0]["open_time"], "o": chunk[0]["o"],
            "h": max(c["h"] for c in chunk), "l": min(c["l"] for c in chunk),
            "c": chunk[-1]["c"], "v": sum(c["v"] for c in chunk),
        })
    return out

def swing_levels(klines, lookback=40):
    """Recent swing high/low (support/resistance) and distance from current price."""
    if len(klines) < 5: return {}
    window = klines[-lookback:]
    hi = max(k["h"] for k in window); lo = min(k["l"] for k in window)
    cur = klines[-1]["c"]
    return {
        "swing_high": hi, "swing_low": lo,
        "dist_to_high_pct": (hi - cur) / cur * 100 if cur else None,
        "dist_to_low_pct": (cur - lo) / cur * 100 if cur else None,
    }

def features(before, interval_min=5):
    """Full point-in-time feature dict from `before` klines (ASC, open_time<anchor)."""
    if len(before) < 30:
        return None
    closes = [k["c"] for k in before]
    highs = [k["h"] for k in before]; lows = [k["l"] for k in before]
    vols = [k["v"] for k in before]
    cur = closes[-1]

    f = {"price": cur, "n_candles": len(before)}
    # --- trend (5m base) ---
    f["ema9"] = ema(closes, 9); f["ema21"] = ema(closes, 21); f["ema50"] = ema(closes, 50)
    f["ema9_gt_21"] = (f["ema9"] or 0) > (f["ema21"] or 0)
    f["ema21_gt_50"] = (f["ema21"] or 0) > (f["ema50"] or 0)
    # --- momentum ---
    f["rsi14"] = rsi(closes, 14)
    f["rsi7"] = rsi(closes, 7)
    macd_line, _ = macd(closes)
    f["macd"] = macd_line
    # --- volatility ---
    a = atr(before, 14)
    f["atr14"] = a
    f["atr_pct"] = (a / cur * 100) if a and cur else None
    # --- returns over windows ---
    def ret(bars):
        return (cur - closes[-bars]) / closes[-bars] * 100 if len(closes) >= bars else None
    f["ret_1h"] = ret(12); f["ret_4h"] = ret(48); f["ret_24h"] = ret(288)
    # --- volume ---
    f["vol_now"] = vols[-1]
    f["vol_avg20"] = sma(vols, 20)
    f["vol_ratio"] = (vols[-1] / f["vol_avg20"]) if f["vol_avg20"] else None
    # --- support/resistance ---
    f.update(swing_levels(before, 48))

    # --- MULTI-TIMEFRAME trend (the key missing signal) ---
    # Use EMA fast/slow sized to the bars actually available per TF, so higher TFs
    # still resolve a trend from limited history (4h needs many 5m bars).
    for fac, name in [(3, "15m"), (12, "1h"), (48, "4h")]:
        rk = resample(before, fac)
        rc = [k["c"] for k in rk]
        if len(rc) >= 10:
            slow = min(21, max(5, len(rc) - 1))
            fast = max(3, slow // 2)
            e9, e21 = ema(rc, fast), ema(rc, slow)
            if e9 is not None and e21 is not None:
                f[f"trend_{name}"] = "up" if e9 > e21 else "down"
            else:
                f[f"trend_{name}"] = None
            f[f"rsi_{name}"] = rsi(rc, min(14, max(5, len(rc) - 1)))
        else:
            f[f"trend_{name}"] = None; f[f"rsi_{name}"] = None

    # --- REVERSAL / BOUNCE-RISK features (the ESPORTS failure gap) ---
    # An oversold coin sitting on support that just crashed is a SHORT trap.
    rsi14 = f["rsi14"] or 50
    ret24 = f["ret_24h"] or 0
    dist_low = f.get("dist_to_low_pct")
    dist_high = f.get("dist_to_high_pct")
    # distance of current price from recent extreme (is it stretched?)
    f["oversold"] = rsi14 < 32
    f["overbought"] = rsi14 > 68
    f["near_support"] = (dist_low is not None and dist_low < 1.5)   # within 1.5% of swing low
    f["near_resistance"] = (dist_high is not None and dist_high < 1.5)
    f["crashed_24h"] = ret24 < -15      # big recent dump
    f["pumped_24h"] = ret24 > 15
    # SHORT bounce-risk: crashed + oversold + near support => shorting a falling knife
    f["short_bounce_risk"] = bool(f["crashed_24h"] and (f["oversold"] or f["near_support"]))
    # LONG fade-risk: pumped + overbought + near resistance
    f["long_fade_risk"] = bool(f["pumped_24h"] and (f["overbought"] or f["near_resistance"]))
    # last-3-candle reversal: did price just bounce hard off the low?
    if len(before) >= 4:
        recent_low = min(k["l"] for k in before[-4:])
        f["bounce_off_low_pct"] = (cur - recent_low) / recent_low * 100 if recent_low else 0
        recent_high = max(k["h"] for k in before[-4:])
        f["fade_off_high_pct"] = (recent_high - cur) / recent_high * 100 if recent_high else 0
    return f

def render(f, ticker):
    """Compact human/LLM-readable snapshot string."""
    def g(k, fmt="{:.4g}"):
        v = f.get(k)
        return fmt.format(v) if isinstance(v, (int, float)) else str(v)
    return (
        f"{ticker} @ analysis time (NO future data)\n"
        f"price={g('price')}  ATR={g('atr_pct')}%\n"
        f"TREND  5m: EMA9{'>' if f['ema9_gt_21'] else '<'}EMA21, EMA21{'>' if f['ema21_gt_50'] else '<'}EMA50 | "
        f"15m={f.get('trend_15m')} 1h={f.get('trend_1h')} 4h={f.get('trend_4h')}\n"
        f"MOMENTUM  RSI14={g('rsi14')} RSI7={g('rsi7')} | RSI 15m={g('rsi_15m')} 1h={g('rsi_1h')}\n"
        f"RETURNS  1h={g('ret_1h')}% 4h={g('ret_4h')}% 24h={g('ret_24h')}%\n"
        f"VOLUME  ratio_vs_20avg={g('vol_ratio')}\n"
        f"LEVELS  swing_high={g('swing_high')} ({g('dist_to_high_pct')}% away)  "
        f"swing_low={g('swing_low')} ({g('dist_to_low_pct')}% away)\n"
        f"REVERSAL FLAGS  oversold={f['oversold']} overbought={f['overbought']} "
        f"near_support={f['near_support']} near_resistance={f['near_resistance']}\n"
        f"  crashed_24h={f['crashed_24h']} pumped_24h={f['pumped_24h']} "
        f"SHORT_bounce_risk={f['short_bounce_risk']} LONG_fade_risk={f['long_fade_risk']}\n"
        f"  bounce_off_4candle_low={g('bounce_off_low_pct')}% fade_off_4candle_high={g('fade_off_high_pct')}%"
    )
