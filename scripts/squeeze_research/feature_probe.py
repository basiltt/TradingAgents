"""Selection-time feature probe.

For every scan, compute — from candles STRICTLY BEFORE the scan's selection
instant (no look-ahead) — a set of features for each candidate, then check
whether any feature separates the squeeze losers from the winners that were
actually picked. Uses the REAL loaded klines via the engine hook.

Pure analysis: hook returns None (pristine run), but records per-candidate
features keyed to the scans where squeezes were picked.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import Any, Optional

from scripts.squeeze_research.harness import BASE_CONFIG, build_service, run_one

SQUEEZE = {"SAHARAUSDT", "TSTBSCUSDT", "POLYXUSDT"}

_CAP: dict[str, Any] = {"rows": []}


def _to_symbol(t: str) -> str:
    return t if t.endswith("USDT") else f"{t}USDT"


def _candles_before(symbol_klines, ts):
    """All candles with open_time < ts (no look-ahead)."""
    out = []
    for k in symbol_klines:
        ot = k["open_time"]
        if ot < ts:
            out.append(k)
        else:
            break
    return out


def _feat(klines_for, ticker, ts):
    """Compute selection-time features for one candidate from prior candles."""
    sk = klines_for.get(ticker, [])
    pre = _candles_before(sk, ts)
    if len(pre) < 13:
        return None
    closes = [c["close"] for c in pre]
    highs = [c["high"] for c in pre]
    lows = [c["low"] for c in pre]
    last = closes[-1]
    if last <= 0:
        return None
    # ATR% over last 14 bars (5m) — realized vol
    trs = []
    for i in range(1, min(15, len(pre))):
        h, l, pc = pre[-i]["high"], pre[-i]["low"], pre[-i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_pct = (sum(trs) / len(trs)) / last * 100 if trs else None
    # momentum: close-to-close over last 12 bars (1h)
    mom_1h = (last - closes[-12]) / closes[-12] * 100 if len(closes) >= 12 else None
    # run-up over last 24 bars (2h): how far it's already pumped from local low
    win = pre[-24:] if len(pre) >= 24 else pre
    lo = min(c["low"] for c in win)
    ru_2h = (last - lo) / lo * 100 if lo > 0 else None
    # distance above EMA20 (extension)
    ema = closes[0]
    k = 2 / (20 + 1)
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    ext = (last - ema) / ema * 100 if ema > 0 else None
    # upper-wick ratio of last bar (rejection vs continuation)
    return {"atr_pct": atr_pct, "mom_1h": mom_1h, "ru_2h": ru_2h, "ext_ema": ext}


def probe_hook(config, signals, klines):
    scans = defaultdict(list)
    for s in signals:
        scans[s["scan_id"]].append(s)
    for sid, sigs in scans.items():
        ts = sigs[0].get("signal_time")
        # mirror batch ranking
        ranked = sorted(sigs, key=lambda s: abs(s.get("score", 0)), reverse=True)
        picked = {_to_symbol(r["ticker"]) for r in ranked[:3] if r.get("ticker")}
        for r in ranked:
            tk = r.get("ticker", "")
            sym = _to_symbol(tk)
            f = _feat(klines, tk, ts)
            if f is None:
                continue
            _CAP["rows"].append({
                "scan": sid[:8], "sym": sym, "score": r.get("score"),
                "dir": r.get("direction"), "picked": sym in picked,
                "is_squeeze": sym in SQUEEZE, **f,
            })
    return None


def _stats(rows, key):
    vals = sorted(r[key] for r in rows if r.get(key) is not None)
    if not vals:
        return "n=0"
    n = len(vals)
    return f"n={n} min={vals[0]:.2f} p25={vals[n//4]:.2f} med={vals[n//2]:.2f} p75={vals[3*n//4]:.2f} max={vals[-1]:.2f}"


async def main() -> None:
    svc, db = await build_service()
    try:
        await run_one(svc, BASE_CONFIG, probe_hook)
        rows = _CAP["rows"]
        sq = [r for r in rows if r["is_squeeze"] and r["picked"]]
        picked_shorts = [r for r in rows if r["picked"] and r["dir"] == "sell"]
        win_shorts = [r for r in picked_shorts if not r["is_squeeze"]]
        print(f"captured {len(rows)} candidate-feature rows")
        print(f"picked squeeze shorts: {len(sq)}   picked winning shorts: {len(win_shorts)}\n")
        for key in ("atr_pct", "mom_1h", "ru_2h", "ext_ema"):
            print(f"feature {key}:")
            print(f"   SQUEEZE picks : {_stats(sq, key)}")
            print(f"   WINNER picks  : {_stats(win_shorts, key)}")
            print()
        # detail on the squeeze rows
        print("squeeze picks detail:")
        for r in sq:
            print(f"   {r['sym']:<12} atr={r['atr_pct']:.2f} mom1h={r['mom_1h']:.2f} "
                  f"ru2h={r['ru_2h']:.2f} ext={r['ext_ema']:.2f}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
