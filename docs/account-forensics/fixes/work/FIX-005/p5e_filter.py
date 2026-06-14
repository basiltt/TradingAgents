"""Phase 5e: quantify the COMBINED deterministic filter on production signals,
across BOTH seeds (generalization). The filter (all proven to generalize):

  KEEP a signal only if:
   - |score| >= MIN_SCORE (conviction), AND
   - NOT a counter-trend trade (short must have 1h+4h downtrend; long must have uptrend), AND
   - NOT a falling-knife short (short_bounce_risk / crashed_24h)

Compares: production-as-is vs filtered, on win-rate, dir-acc, dir-pnl, and trade count.
"""
import json

def trend_aligned(x):
    t1, t4 = x["features"].get("trend_1h"), x["features"].get("trend_4h")
    if x["prod_dir"] == "sell":
        return t1 == "down" and t4 == "down"
    if x["prod_dir"] == "buy":
        return t1 == "up" and t4 == "up"
    return False

def falling_knife_short(x):
    return x["prod_dir"] == "sell" and (
        x["features"].get("short_bounce_risk") or x["features"].get("crashed_24h"))

def metrics(rows):
    if not rows: return (0, 0, 0, 0)
    win = sum(1 for x in rows if x["prod_outcome"]["win"]) / len(rows) * 100
    pnl = sum((x["fwd_ret_8h"] if x["prod_dir"] == "buy" else -x["fwd_ret_8h"]) for x in rows) / len(rows)
    dec = [x for x in rows if abs(x["fwd_ret_8h"]) > 0.2]
    acc = sum(1 for x in dec if (x["prod_dir"] == "buy") == (x["fwd_ret_8h"] > 0)) / len(dec) * 100 if dec else 0
    return (round(win, 1), round(acc, 1), round(pnl, 3), len(rows))

def apply_filter(rows, min_score):
    return [x for x in rows
            if abs(x["prod_score"]) >= min_score
            and trend_aligned(x)
            and not falling_knife_short(x)]

for min_score in [6, 7]:
    print(f"\n{'='*70}\nFILTER: min_score>={min_score} + trend-aligned + no-falling-knife\n{'='*70}")
    for seed in [42, 99]:
        d = json.load(open(f"_dataset_150_{seed}_6.json"))
        base = metrics(d)
        filt = metrics(apply_filter(d, min_score))
        kept = filt[3] / len(d) * 100
        print(f"  seed{seed}: BASE win={base[0]}% acc={base[1]}% pnl={base[2]:+.2f}% n={base[3]}")
        print(f"          FILT win={filt[0]}% acc={filt[1]}% pnl={filt[2]:+.2f}% n={filt[3]} (kept {kept:.0f}%)")
    # combined both seeds
    allrows = json.load(open("_dataset_150_42_6.json")) + json.load(open("_dataset_150_99_6.json"))
    b = metrics(allrows); f = metrics(apply_filter(allrows, min_score))
    print(f"  COMBINED: BASE win={b[0]}% acc={b[1]}% pnl={b[2]:+.2f}% n={b[3]}  ->  "
          f"FILT win={f[0]}% acc={f[1]}% pnl={f[2]:+.2f}% n={f[3]} (kept {f[3]/b[3]*100:.0f}%)")
