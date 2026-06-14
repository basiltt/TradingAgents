"""Phase 5b: held-out validation + reproducibility for the WINNING strategy.

1. Re-run the winning strategy on a FRESH seed (different signals) -> guards overfit.
2. Reproducibility: run the SAME held-out signals 3x with single-call vs ensemble,
   measure call-stability (% of signals whose final call is identical across runs).

Usage: python p5_validate.py <strategy_name> [n] [seed]
"""
import sys, asyncio, json, os
sys.path.insert(0, ".")
from p4_engine import build_dataset
import strategies as STRAT
from _ensemble import ensemble_call, _one_call
from _harness import label_outcome

async def score_calls(data, get_call):
    """get_call(d) -> (dir, meta). Score against ground truth."""
    traded = wins = 0; shorts = longs = 0; sw = lw = 0
    rs = []
    per = []
    for d in data:
        dirc, meta = await get_call(d)
        if dirc == "buy": out = d["long_outcome"]
        elif dirc == "sell": out = d["short_outcome"]
        else: out = None
        if out:
            traded += 1
            if out["win"]: wins += 1
            if out["r_multiple"] is not None: rs.append(out["r_multiple"])
            if dirc == "sell":
                shorts += 1; sw += 1 if out["win"] else 0
            else:
                longs += 1; lw += 1 if out["win"] else 0
        per.append((d["id"], dirc, meta))
    return {
        "traded": traded, "win_rate": round(wins / traded * 100, 1) if traded else 0,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else 0,
        "abstained": len(data) - traded,
        "short": shorts, "short_wr": round(sw / shorts * 100, 1) if shorts else 0,
        "long": longs, "long_wr": round(lw / longs * 100, 1) if longs else 0,
    }, per

async def main(strategy_name, n=150, seed=99):
    data = await build_dataset(n, seed, 6)
    strat = getattr(STRAT, strategy_name)
    print(f"\n=== HELD-OUT VALIDATION: '{strategy_name}' on seed={seed}, {len(data)} signals ===")

    # single-call
    loop = asyncio.get_event_loop()
    async def single(d):
        dirc, conf = await loop.run_in_executor(None, _one_call, strat(d["ticker"], d["features"]), 0.7)
        return (dirc if dirc in ("buy", "sell") else "none"), {"conf": conf}
    s_single, _ = await score_calls(data, single)
    print(f"SINGLE-CALL: win={s_single['win_rate']}% exp={s_single['expectancy_r']}R "
          f"traded={s_single['traded']} abst={s_single['abstained']} "
          f"short={s_single['short']}({s_single['short_wr']}%) long={s_single['long']}({s_single['long_wr']}%)")

    # ensemble (5-vote)
    async def ens(d):
        winner, agree, conf, votes = await ensemble_call(strat(d["ticker"], d["features"]), n=5)
        return (winner if winner in ("buy", "sell") else "none"), {"agree": agree, "conf": conf}
    s_ens, ens_calls = await score_calls(data, ens)
    print(f"ENSEMBLE-5:  win={s_ens['win_rate']}% exp={s_ens['expectancy_r']}R "
          f"traded={s_ens['traded']} abst={s_ens['abstained']} "
          f"short={s_ens['short']}({s_ens['short_wr']}%) long={s_ens['long']}({s_ens['long_wr']}%)")

    # reproducibility: run ensemble AGAIN, compare calls per signal
    s_ens2, ens_calls2 = await score_calls(data, ens)
    c1 = {i: d for i, d, _ in ens_calls}
    c2 = {i: d for i, d, _ in ens_calls2}
    same = sum(1 for i in c1 if c1[i] == c2.get(i))
    print(f"REPRODUCIBILITY (ensemble run1 vs run2): {same}/{len(c1)} identical calls "
          f"({same/len(c1)*100:.0f}%)  [run2 win={s_ens2['win_rate']}%]")
    print(f"BASELINE to beat: 56.7% win, +0.307R")

if __name__ == "__main__":
    name = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    asyncio.run(main(name, n, seed))
