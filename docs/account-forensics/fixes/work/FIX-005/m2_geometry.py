"""Method C: TP/SL geometry. Win-rate is path-dependent on the LEVELS, not just
direction. Production signals set their own SL/TP; the research showed good direction
but tight SL -> stopped out. Test alternative TP/SL geometries on the SAME signals
(direction + entry fixed) to see which maximizes TP-before-SL on BOTH seeds.

For each geometry we re-simulate the path over forward 5m candles with the new
levels and recompute win-rate. We pair this with the best deterministic filter
(score>=7 + trend3tf + no_knife) so we're optimizing the geometry of the GOOD signals.
"""
import json, sys
sys.path.insert(0, ".")
from _harness import connect, klines_after, run

SEEDS = [42, 99]
DATA = {s: json.load(open(f"_dataset_150_{s}_6.json")) for s in SEEDS}

def f(x, k): return x["features"].get(k)
def trend3tf(x):
    t15, t1, t4 = f(x,"trend_15m"), f(x,"trend_1h"), f(x,"trend_4h")
    if not (t15 and t1 and t4): return True
    want = "up" if x["prod_dir"]=="buy" else "down"
    return t15==want and t1==want and t4==want
def no_knife(x):
    if x["prod_dir"]!="sell": return True
    return not (f(x,"short_bounce_risk") or f(x,"crashed_24h"))
def keep(x): return abs(x["prod_score"])>=7 and trend3tf(x) and no_knife(x)

def simulate(direction, entry, sl, tp, after, atr_pct=None):
    """Path sim: return True if TP hit before SL over forward candles."""
    is_short = direction in ("sell","short")
    for k in after:
        hi, lo = k["h"], k["l"]
        sl_hit = (hi>=sl) if is_short else (lo<=sl)
        tp_hit = (lo<=tp) if is_short else (hi>=tp)
        if sl_hit and tp_hit: return False  # conservative: SL first
        if sl_hit: return False
        if tp_hit: return True
    # timeout: judge by final close
    final = after[-1]["c"]
    return (final<entry) if is_short else (final>entry)

# geometries: (name, tp_pct, sl_pct) as fraction of entry, OR atr-based
GEOMS = [
    ("prod_levels", None, None),       # use the signal's own SL/TP (baseline)
    ("tp1.0/sl1.5", 0.010, 0.015),     # wider SL, nearer TP -> higher hit rate
    ("tp0.8/sl1.5", 0.008, 0.015),
    ("tp0.6/sl1.2", 0.006, 0.012),
    ("tp1.0/sl2.0", 0.010, 0.020),     # much wider SL (let it breathe)
    ("tp1.5/sl2.0", 0.015, 0.020),
    ("atr_tp1.0/sl2.0", "atr", "atr"), # ATR-scaled (handled below)
]

async def main():
    conn = await connect()
    # cache forward klines per (seed,id)
    fwd = {}
    for s in SEEDS:
        for x in DATA[s]:
            if keep(x):
                import datetime as dt
                anchor = dt.datetime.fromisoformat(str(x.get("anchor")).replace("Z","+00:00")) if x.get("anchor") else None
                # we didn't store anchor in dataset; refetch via id->ticker + stored? fallback: skip
    # The dataset stored prod_outcome but not raw forward klines or anchor. Re-fetch.
    # Need ticker + anchor; dataset has ticker but not anchor. Pull anchor from DB by id.
    rows = await conn.fetch("""
        select sr.id, sr.ticker, s.started_at anchor from scan_results sr
        join scans s on s.scan_id=sr.scan_id where sr.id = any($1::int[])
    """, [x["id"] for s in SEEDS for x in DATA[s] if keep(x)])
    anchors = {r["id"]: (r["ticker"], r["anchor"]) for r in rows}
    import datetime as dt
    for s in SEEDS:
        for x in DATA[s]:
            if not keep(x): continue
            if x["id"] not in anchors: continue
            tk, anc = anchors[x["id"]]
            anchor = dt.datetime.fromisoformat(str(anc).replace("Z","+00:00"))
            after = await klines_after(conn, tk, anchor, n=96)
            fwd[(s, x["id"])] = after
    await conn.close()

    print(f"{'geometry':<18}" + "".join(f"seed{s:<10}" for s in SEEDS))
    print("="*48)
    for name, tp_p, sl_p in GEOMS:
        line = f"{name:<18}"
        for s in SEEDS:
            kept = [x for x in DATA[s] if keep(x) and (s, x["id"]) in fwd]
            wins = tot = 0
            for x in kept:
                after = fwd[(s, x["id"])]
                if not after: continue
                entry = after[0]["o"]; direction = x["prod_dir"]
                is_short = direction=="sell"
                if tp_p is None:  # prod levels
                    sl = (x["sl"] if "sl" in x else None)
                    ds = x  # dataset doesn't carry sl/tp directly; use prod_outcome
                    # fall back: prod_outcome already computed -> reuse
                    w = x["prod_outcome"]["win"]
                elif tp_p == "atr":
                    ap = (f(x,"atr_pct") or 1.0)/100
                    tp = entry*(1-ap) if is_short else entry*(1+ap)
                    sl = entry*(1+2*ap) if is_short else entry*(1-2*ap)
                    w = simulate(direction, entry, sl, tp, after)
                else:
                    tp = entry*(1-tp_p) if is_short else entry*(1+tp_p)
                    sl = entry*(1+sl_p) if is_short else entry*(1-sl_p)
                    w = simulate(direction, entry, sl, tp, after)
                wins += 1 if w else 0; tot += 1
            wr = round(wins/tot*100,1) if tot else 0
            line += f"{f'{wr}%/{tot}':<14}"
        print(line)

run(main())
