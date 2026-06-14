"""Method A+B: systematic filter-stacking + LLM-agreement search over BOTH seeds.

Reuses cached datasets (features + ground-truth outcomes) and saved LLM calls.
Evaluates many candidate filters and their combinations, reporting win-rate + trade
count on seed42 AND seed99. A combo only counts if it clears the bar on BOTH (no
overfitting to one sample).

Win metric = prod_outcome['win'] (path-dependent TP/SL on the production signal's own
levels) — the same metric the shipped filter improved.
"""
import json

SEEDS = [42, 99]
DATA = {s: json.load(open(f"_dataset_150_{s}_6.json")) for s in SEEDS}
# index by id for LLM-call joins
BYID = {s: {x["id"]: x for x in DATA[s]} for s in SEEDS}
LLM = {}
for s in SEEDS:
    try:
        LLM[s] = {c["id"]: c for c in json.load(open(f"result_final_v1_{s}.json"))["calls"]}
    except FileNotFoundError:
        LLM[s] = {}

def f(x, k): return x["features"].get(k)

# ---- candidate predicates (each returns True = KEEP the signal) ----
def trend_aligned(x):
    t1, t4 = f(x, "trend_1h"), f(x, "trend_4h")
    if not (t1 and t4): return True  # fail-open
    want = "up" if x["prod_dir"] == "buy" else "down"
    return t1 == want and t4 == want

def not_falling_knife(x):
    if x["prod_dir"] != "sell": return True
    return not (f(x, "short_bounce_risk") or f(x, "crashed_24h"))

def score_ge(n): return lambda x: abs(x["prod_score"]) >= n

def rsi_room_short(x):
    # short only if RSI not already oversold (room to fall). RSI14 > 38 for shorts.
    if x["prod_dir"] != "sell": return True
    r = f(x, "rsi14")
    return r is None or r > 38

def rsi_room_long(x):
    if x["prod_dir"] != "buy": return True
    r = f(x, "rsi14")
    return r is None or r < 62

def vol_confirm(x):
    vr = f(x, "vol_ratio")
    return vr is None or vr >= 1.0  # at/above avg volume

def trend_3tf(x):
    # all of 15m,1h,4h aligned (stricter than 1h+4h)
    t15, t1, t4 = f(x, "trend_15m"), f(x, "trend_1h"), f(x, "trend_4h")
    if not (t15 and t1 and t4): return True
    want = "up" if x["prod_dir"] == "buy" else "down"
    return t15 == want and t1 == want and t4 == want

def llm_agree(x, seed):
    c = LLM[seed].get(x["id"])
    if not c or c.get("llm_dir") not in ("buy", "sell"):
        return True  # no LLM opinion -> fail-open (don't drop)
    return c["llm_dir"] == x["prod_dir"]

def not_overbought_short(x):
    # avoid shorting after it's already dumped hard on the day AND bouncing
    if x["prod_dir"] != "sell": return True
    bounce = f(x, "bounce_off_low_pct")
    return bounce is None or bounce < 1.5  # not mid-bounce

CANDS = {
    "score>=6": score_ge(6), "score>=7": score_ge(7), "score>=8": score_ge(8),
    "trend2tf": trend_aligned, "trend3tf": trend_3tf, "no_knife": not_falling_knife,
    "rsi_room_S": rsi_room_short, "rsi_room_L": rsi_room_long,
    "vol>=avg": vol_confirm, "not_mid_bounce": not_overbought_short,
}

def wr(rows):
    if not rows: return (0.0, 0)
    w = sum(1 for x in rows if x["prod_outcome"]["win"]) / len(rows) * 100
    return (round(w, 1), len(rows))

def apply(seed, preds, use_llm=False):
    rows = DATA[seed]
    out = []
    for x in rows:
        if all(p(x) for p in preds) and (not use_llm or llm_agree(x, seed)):
            out.append(x)
    return out

# baselines
print("BASELINE per seed:")
for s in SEEDS:
    print(f"  seed{s}: win={wr(DATA[s])[0]}% n={wr(DATA[s])[1]}")

# single filters
print("\nSINGLE FILTERS (win% / n):")
for name, p in CANDS.items():
    r = " | ".join(f"s{s}:{wr(apply(s,[p]))[0]}%/{wr(apply(s,[p]))[1]}" for s in SEEDS)
    print(f"  {name:<16} {r}")

print("\nLLM-AGREEMENT alone (final_v1 agrees with prod dir):")
for s in SEEDS:
    r = apply(s, [], use_llm=True); print(f"  seed{s}: win={wr(r)[0]}% n={wr(r)[1]}")

# ---- combination search ----
import itertools
print("\n" + "="*78)
print("COMBO SEARCH (must clear bar on BOTH seeds, n>=25 each):")
print("="*78)
# pool of generalizing filters (drop the seed-specific ones)
POOL = {
    "score>=7": score_ge(7), "score>=8": score_ge(8),
    "trend2tf": trend_aligned, "trend3tf": trend_3tf,
    "no_knife": not_falling_knife, "not_mid_bounce": not_overbought_short,
}
results = []
names = list(POOL.keys())
for r in range(1, 5):
    for combo in itertools.combinations(names, r):
        preds = [POOL[c] for c in combo]
        for use_llm in [False, True]:
            seed_stats = {s: wr(apply(s, preds, use_llm)) for s in SEEDS}
            w42, n42 = seed_stats[42]; w99, n99 = seed_stats[99]
            if n42 >= 25 and n99 >= 25:
                tag = "+LLM" if use_llm else ""
                results.append((min(w42, w99), w42, n42, w99, n99, "+".join(combo)+tag))
# sort by worst-seed win rate (the generalization bar)
results.sort(reverse=True)
print(f"{'min_win':<9}{'s42':<14}{'s99':<14}{'filters'}")
for minw, w42, n42, w99, n99, name in results[:18]:
    print(f"{minw:<9}{f'{w42}%/{n42}':<14}{f'{w99}%/{n99}':<14}{name}")
