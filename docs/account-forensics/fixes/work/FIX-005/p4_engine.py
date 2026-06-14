"""Phase 4: LLM signal-replay engine. The core of the iteration loop.

For each historical signal: rebuild point-in-time features, ask the production model
(MiniMax-M2.7-highspeed) for a directional call under a given STRATEGY (prompt), score
that call against ground-truth path-dependent outcomes, aggregate accuracy.

Strategies are pluggable (strategies.py). Runs concurrently (unlimited LLM budget).
Caches features+outcomes per signal so re-runs with new prompts don't re-query klines.

Usage:
  python p4_engine.py <strategy_name> [n] [seed]
  python p4_engine.py baseline_prompt 200 42
"""
from __future__ import annotations
import sys, os, json, asyncio, datetime as dt
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv("../.env"); load_dotenv(".env")
from _harness import (connect, fetch_signals, klines_before, klines_after,
                      label_outcome, entry_from, p)
from _features import features
from anthropic import Anthropic
import strategies as STRAT

MODEL = "MiniMax-M2.7-highspeed"
KEY = os.getenv("MINIMAX_API_KEY", "")
CLIENT = Anthropic(api_key=KEY, base_url="https://api.minimax.io/anthropic", timeout=90, max_retries=2)
CONCURRENCY = 10  # parallel LLM calls
import threading
from concurrent.futures import ThreadPoolExecutor
_POOL = ThreadPoolExecutor(max_workers=CONCURRENCY)
_progress = {"done": 0, "total": 0, "lock": threading.Lock()}

def llm_text(resp):
    return "\n".join(b.text for b in (resp.content or [])
                     if getattr(b, "type", None) == "text" and getattr(b, "text", None)).strip()

def call_llm(prompt):
    out = {"call": "ERR", "confidence": 0, "reason": "no_json"}
    for _ in range(2):
        try:
            m = CLIENT.messages.create(model=MODEL, max_tokens=1200,
                                       messages=[{"role": "user", "content": prompt}])
            txt = llm_text(m)
            if "{" in txt and "}" in txt:
                out = json.loads(txt[txt.find("{"):txt.rfind("}") + 1]); break
        except Exception:
            pass
    with _progress["lock"]:
        _progress["done"] += 1
        d, t = _progress["done"], _progress["total"]
    if d % 10 == 0 or d == t:
        print(f"  ... {d}/{t} calls done", flush=True)
    return out

async def build_dataset(n, seed, min_score=6):
    """Fetch signals + reconstruct features + ground-truth outcomes once (cached)."""
    cache_f = f"_dataset_{n}_{seed}_{min_score}.json"
    if os.path.exists(cache_f):
        with open(cache_f) as f:
            return json.load(f)
    conn = await connect()
    sigs = await fetch_signals(conn, min_abs_score=min_score, limit=n, seed=seed)
    data = []
    for s in sigs:
        before = await klines_before(conn, s["ticker"], s["anchor"], n=1000)  # ~83h for 4h EMAs
        after = await klines_after(conn, s["ticker"], s["anchor"], n=96)
        f = features(before)
        if not f or not after:
            continue
        entry = entry_from(after, s["ds"].get("entry_price"))
        sl = (s["ds"].get("stop_losses") or [None])[0]; tps = s["ds"].get("take_profits") or []
        out = label_outcome(s["direction"], entry, sl, tps, after)
        if out is None:
            continue
        # Also compute outcomes for BOTH directions (so we can score LLM flips)
        out_long = label_outcome("buy", entry, entry * 0.99, [entry * 1.015], after)
        out_short = label_outcome("sell", entry, entry * 1.01, [entry * 0.985], after)
        data.append({
            "id": s["id"], "ticker": s["ticker"], "prod_dir": s["direction"],
            "prod_score": s["score"], "features": f,
            "prod_outcome": out, "long_outcome": out_long, "short_outcome": out_short,
            "fwd_ret_8h": round((after[min(95, len(after)-1)]["c"] - entry) / entry * 100, 2),
        })
    await conn.close()
    with open(cache_f, "w") as fh:
        json.dump(data, fh)
    return data

async def run_strategy(strategy_name, n=200, seed=42, min_score=6):
    data = await build_dataset(n, seed, min_score)
    strat = getattr(STRAT, strategy_name)
    p(f"STRATEGY '{strategy_name}' on {len(data)} signals (seed={seed})")

    sem = asyncio.Semaphore(CONCURRENCY)
    results = [None] * len(data)
    loop = asyncio.get_event_loop()
    _progress["done"] = 0; _progress["total"] = len(data)
    print(f"  dispatching {len(data)} LLM calls (concurrency={CONCURRENCY})...", flush=True)

    async def worker(i, d):
        async with sem:
            prompt = strat(d["ticker"], d["features"])
            j = await loop.run_in_executor(_POOL, call_llm, prompt)
            results[i] = (d, j)

    await asyncio.gather(*(worker(i, d) for i, d in enumerate(data)))

    # ---- score the LLM's calls ----
    scored = []
    for d, j in results:
        call = (j.get("call") or "").lower()
        if call in ("short", "sell"):
            llm_dir = "sell"; outcome = d["short_outcome"]
        elif call in ("long", "buy"):
            llm_dir = "buy"; outcome = d["long_outcome"]
        else:  # No Trade / ERR -> abstain
            llm_dir = "none"; outcome = None
        scored.append({**d, "llm": j, "llm_dir": llm_dir, "llm_outcome": outcome})

    traded = [s for s in scored if s["llm_dir"] != "none"]
    abstained = [s for s in scored if s["llm_dir"] == "none"]
    wins = [s for s in traded if s["llm_outcome"] and s["llm_outcome"]["win"]]
    wr = len(wins) / len(traded) * 100 if traded else 0
    # Directional hit: did the LLM call match the sign of the 8h forward return?
    # (clean metric, independent of synthetic TP/SL). Threshold 0.2% to ignore noise.
    def dir_hit(s):
        r = s["fwd_ret_8h"]
        if s["llm_dir"] == "buy":  return r > 0.2
        if s["llm_dir"] == "sell": return r < -0.2
        return None
    dir_hits = [s for s in traded if dir_hit(s)]
    dir_decided = [s for s in traded if abs(s["fwd_ret_8h"]) > 0.2]
    dir_acc = len(dir_hits) / len(dir_decided) * 100 if dir_decided else 0
    # Directional PnL: mean 8h forward return in the CALLED direction (long=+ret, short=-ret).
    # Positive => the calls have genuine directional edge, independent of synthetic SL/TP.
    dir_pnls = [(s["fwd_ret_8h"] if s["llm_dir"] == "buy" else -s["fwd_ret_8h"]) for s in traded]
    dir_pnl = sum(dir_pnls) / len(dir_pnls) if dir_pnls else 0
    rs = [s["llm_outcome"]["r_multiple"] for s in traded if s["llm_outcome"] and s["llm_outcome"]["r_multiple"] is not None]
    exp_r = sum(rs) / len(rs) if rs else 0
    shorts = [s for s in traded if s["llm_dir"] == "sell"]
    longs = [s for s in traded if s["llm_dir"] == "buy"]
    sw = sum(1 for s in shorts if s["llm_outcome"]["win"]) / len(shorts) * 100 if shorts else 0
    lw = sum(1 for s in longs if s["llm_outcome"]["win"]) / len(longs) * 100 if longs else 0
    # agreement with prod
    agree = sum(1 for s in traded if s["llm_dir"] == s["prod_dir"])

    p(f"RESULTS '{strategy_name}'")
    print(f"  signals:        {len(scored)}  traded={len(traded)}  abstained(No-Trade)={len(abstained)}")
    print(f"  WIN RATE:       {wr:.1f}%  ({len(wins)}/{len(traded)})")
    print(f"  DIR ACCURACY:   {dir_acc:.1f}%  (call matches 8h fwd-return sign, {len(dir_hits)}/{len(dir_decided)})")
    print(f"  DIR PnL:        {dir_pnl:+.3f}%  (mean 8h fwd-return in called direction)")
    print(f"  expectancy:     {exp_r:+.3f} R")
    print(f"  short {len(shorts)} ({sw:.0f}% win) / long {len(longs)} ({lw:.0f}% win)")
    print(f"  agreement w/prod-direction: {agree}/{len(traded)} ({agree/len(traded)*100:.0f}%)" if traded else "")
    print(f"  abstention rate: {len(abstained)/len(scored)*100:.0f}%  (filtering low-quality setups)")

    res = {"strategy": strategy_name, "n": len(scored), "traded": len(traded),
           "abstained": len(abstained), "win_rate": round(wr, 1), "dir_acc": round(dir_acc, 1),
           "dir_pnl": round(dir_pnl, 3), "expectancy_r": round(exp_r, 3),
           "short_n": len(shorts), "short_wr": round(sw, 1), "long_n": len(longs), "long_wr": round(lw, 1)}
    with open(f"result_{strategy_name}_{seed}.json", "w") as fh:
        json.dump({**res, "calls": [{"id": s["id"], "ticker": s["ticker"], "llm_dir": s["llm_dir"],
                   "conf": s["llm"].get("confidence"), "win": s["llm_outcome"]["win"] if s["llm_outcome"] else None}
                   for s in scored]}, fh, indent=2)
    return res

if __name__ == "__main__":
    name = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    asyncio.run(run_strategy(name, n, seed))
