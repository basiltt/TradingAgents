"""Phase 5: ensemble (self-consistency) on a lean strategy.

Runs the winning lean prompt N times per signal, majority-votes, scores accuracy AND
measures reproducibility (run the whole thing twice, compare per-signal calls).

Usage: python p5_ensemble.py <strategy> [n_signals] [seed] [votes]
"""
import sys, asyncio, json, os
sys.path.insert(0, ".")
from p4_engine import build_dataset
import strategies as STRAT
from _ensemble import ensemble_call

async def score(data, strat, votes, temperature=0.3):
    sem = asyncio.Semaphore(8)
    calls = {}
    async def one(d):
        async with sem:
            f = d["features"]
            # trend hint for tie-break: align with 1h/4h trend when they agree
            t1, t4 = f.get("trend_1h"), f.get("trend_4h")
            hint = None
            if t1 == t4 == "up": hint = "buy"
            elif t1 == t4 == "down": hint = "sell"
            winner, agree, conf, votes_list = await ensemble_call(
                strat(d["ticker"], f), n=votes, temperature=temperature, trend_hint=hint)
            calls[d["id"]] = (winner, agree, conf)
    await asyncio.gather(*(one(d) for d in data))
    # score
    traded = wins = 0; rs = []; sh = lo = shw = low = 0
    for d in data:
        winner, agree, conf = calls[d["id"]]
        if winner == "buy": out = d["long_outcome"]
        elif winner == "sell": out = d["short_outcome"]
        else: out = None
        if out:
            traded += 1; wins += 1 if out["win"] else 0
            if out["r_multiple"] is not None: rs.append(out["r_multiple"])
            if winner == "sell": sh += 1; shw += 1 if out["win"] else 0
            else: lo += 1; low += 1 if out["win"] else 0
    return {
        "win_rate": round(wins/traded*100, 1) if traded else 0,
        "expectancy_r": round(sum(rs)/len(rs), 3) if rs else 0,
        "traded": traded, "abstained": len(data)-traded,
        "short": sh, "short_wr": round(shw/sh*100, 1) if sh else 0,
        "long": lo, "long_wr": round(low/lo*100, 1) if lo else 0,
    }, calls

async def main(strategy, n=150, seed=42, votes=5):
    data = await build_dataset(n, seed, 6)
    strat = getattr(STRAT, strategy)
    print(f"\n=== ENSEMBLE-{votes} '{strategy}' on {len(data)} signals (seed={seed}) ===", flush=True)
    print("BASELINE to beat: 56.7% win, +0.307R\n", flush=True)

    s1, c1 = await score(data, strat, votes)
    print(f"RUN 1: win={s1['win_rate']}% exp={s1['expectancy_r']}R traded={s1['traded']} "
          f"abst={s1['abstained']} short={s1['short']}({s1['short_wr']}%) long={s1['long']}({s1['long_wr']}%)", flush=True)

    # reproducibility: second full ensemble run, compare calls
    s2, c2 = await score(data, strat, votes)
    same = sum(1 for k in c1 if c1[k][0] == c2.get(k, (None,))[0])
    print(f"RUN 2: win={s2['win_rate']}% exp={s2['expectancy_r']}R traded={s2['traded']}", flush=True)
    print(f"REPRODUCIBILITY: {same}/{len(c1)} identical calls ({same/len(c1)*100:.0f}%)", flush=True)

    json.dump({"strategy": strategy, "votes": votes, "run1": s1, "run2": s2,
               "reproducibility_pct": round(same/len(c1)*100, 1)},
              open(f"ensemble_{strategy}_{seed}.json", "w"), indent=2)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv)>2 else 150,
                     int(sys.argv[3]) if len(sys.argv)>3 else 42,
                     int(sys.argv[4]) if len(sys.argv)>4 else 5))
