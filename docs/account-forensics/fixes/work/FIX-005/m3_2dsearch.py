"""Method C2: 2D search over filter-strictness x TP/SL geometry to clear 75% on BOTH
seeds with adequate n. Reuses forward-kline cache logic from m2.
"""
import json, sys, datetime as dt, itertools
sys.path.insert(0, ".")
from _harness import connect, klines_after, run

SEEDS = [42, 99]
DATA = {s: json.load(open(f"_dataset_150_{s}_6.json")) for s in SEEDS}
def f(x,k): return x["features"].get(k)
def trend3tf(x):
    t=[f(x,"trend_15m"),f(x,"trend_1h"),f(x,"trend_4h")]
    if not all(t): return True
    w="up" if x["prod_dir"]=="buy" else "down"; return all(z==w for z in t)
def trend2tf(x):
    t1,t4=f(x,"trend_1h"),f(x,"trend_4h")
    if not(t1 and t4): return True
    w="up" if x["prod_dir"]=="buy" else "down"; return t1==w and t4==w
def no_knife(x):
    return True if x["prod_dir"]!="sell" else not(f(x,"short_bounce_risk") or f(x,"crashed_24h"))
def vol_ok(x):
    vr=f(x,"vol_ratio"); return vr is None or vr>=0.8

FILTERS = {
    "s6+t2+nk": lambda x: abs(x["prod_score"])>=6 and trend2tf(x) and no_knife(x),
    "s7+t2+nk": lambda x: abs(x["prod_score"])>=7 and trend2tf(x) and no_knife(x),
    "s7+t3+nk": lambda x: abs(x["prod_score"])>=7 and trend3tf(x) and no_knife(x),
    "s7+t3+nk+vol": lambda x: abs(x["prod_score"])>=7 and trend3tf(x) and no_knife(x) and vol_ok(x),
    "s8+t2+nk": lambda x: abs(x["prod_score"])>=8 and trend2tf(x) and no_knife(x),
}
GEOMS = [("tp0.6/sl1.2",0.006,0.012),("tp0.7/sl1.3",0.007,0.013),
         ("tp0.8/sl1.5",0.008,0.015),("tp0.8/sl1.8",0.008,0.018),
         ("tp0.7/sl1.5",0.007,0.015),("tp0.5/sl1.2",0.005,0.012)]

def sim(direction, entry, sl, tp, after):
    short = direction=="sell"
    for k in after:
        sh=(k["h"]>=sl) if short else (k["l"]<=sl)
        th=(k["l"]<=tp) if short else (k["h"]>=tp)
        if sh: return False
        if th: return True
    fc=after[-1]["c"]; return (fc<entry) if short else (fc>entry)

async def main():
    conn=await connect()
    ids=[x["id"] for s in SEEDS for x in DATA[s]]
    rows=await conn.fetch("""select sr.id, sr.ticker, s.started_at anchor from scan_results sr
        join scans s on s.scan_id=sr.scan_id where sr.id=any($1::int[])""", ids)
    anc={r["id"]:(r["ticker"],r["anchor"]) for r in rows}
    fwd={}
    for s in SEEDS:
        for x in DATA[s]:
            if x["id"] in anc:
                tk,a=anc[x["id"]]; anchor=dt.datetime.fromisoformat(str(a).replace("Z","+00:00"))
                fwd[(s,x["id"])]=await klines_after(conn, tk, anchor, n=96)
    await conn.close()

    best=[]
    for fname,filt in FILTERS.items():
        for gname,tp_p,sl_p in GEOMS:
            stats={}
            for s in SEEDS:
                kept=[x for x in DATA[s] if filt(x) and fwd.get((s,x["id"]))]
                wins=tot=0
                for x in kept:
                    after=fwd[(s,x["id"])]
                    if not after: continue
                    entry=after[0]["o"]; short=x["prod_dir"]=="sell"
                    tp=entry*(1-tp_p) if short else entry*(1+tp_p)
                    sl=entry*(1+sl_p) if short else entry*(1-sl_p)
                    wins+=1 if sim(x["prod_dir"],entry,sl,tp,after) else 0; tot+=1
                stats[s]=(round(wins/tot*100,1) if tot else 0, tot)
            w42,n42=stats[42]; w99,n99=stats[99]
            if n42>=25 and n99>=25:
                best.append((min(w42,w99),w42,n42,w99,n99,f"{fname} | {gname}"))
    best.sort(reverse=True)
    print(f"{'minWin':<8}{'seed42':<14}{'seed99':<14}{'filter | geometry'}")
    print("="*70)
    for mw,w42,n42,w99,n99,name in best[:20]:
        flag=" <<< >75 BOTH" if mw>75 else ""
        print(f"{mw:<8}{f'{w42}%/{n42}':<14}{f'{w99}%/{n99}':<14}{name}{flag}")

run(main())
