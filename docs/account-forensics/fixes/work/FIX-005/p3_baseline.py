"""Phase 3a: BASELINE — score the CURRENT system's recorded signals against
ground-truth path-dependent outcomes. No LLM calls — just: did the signals the
production system actually emitted make money?

This is the bar to beat. Run on a fixed seed sample so it's reproducible.
"""
import sys; sys.path.insert(0, ".")
from _harness import (connect, fetch_signals, klines_after, label_outcome,
                      entry_from, p, run)

async def main(n=300):
    conn = await connect()
    sigs = await fetch_signals(conn, min_abs_score=6, limit=n, seed=42)
    p(f"BASELINE: scoring {len(sigs)} current-system signals (|score|>=6, seed=42)")
    results = []
    for s in sigs:
        ds = s["ds"]
        direction = s["direction"]
        tt = ds.get("trade_type", "")
        if tt == "No Trade" or direction not in ("buy", "sell"):
            continue
        after = await klines_after(conn, s["ticker"], s["anchor"], n=96)
        if not after:
            continue
        entry = entry_from(after, ds.get("entry_price"))
        sl = (ds.get("stop_losses") or [None])[0]
        tps = ds.get("take_profits") or []
        out = label_outcome(direction, entry, sl, tps, after)
        if out is None:
            continue
        results.append({**s, "out": out, "entry": entry, "sl": sl, "tps": tps})
    await conn.close()

    # ---- aggregate ----
    n_tot = len(results)
    wins = sum(1 for r in results if r["out"]["win"])
    tp_first = sum(1 for r in results if r["out"]["result"] == "tp")
    sl_first = sum(1 for r in results if r["out"]["result"] == "sl")
    timeouts = sum(1 for r in results if r["out"]["result"] == "timeout")
    shorts = [r for r in results if r["direction"] == "sell"]
    longs = [r for r in results if r["direction"] == "buy"]
    avg_mfe = sum(r["out"]["mfe_pct"] for r in results) / n_tot if n_tot else 0
    avg_mae = sum(r["out"]["mae_pct"] for r in results) / n_tot if n_tot else 0
    rs = [r["out"]["r_multiple"] for r in results if r["out"]["r_multiple"] is not None]
    exp_r = sum(rs) / len(rs) if rs else 0

    p("BASELINE RESULTS")
    print(f"  signals scored:        {n_tot}")
    print(f"  WIN RATE (TP before SL): {wins/n_tot*100:.1f}%  ({wins}/{n_tot})")
    print(f"  outcome: tp_first={tp_first} ({tp_first/n_tot*100:.0f}%)  "
          f"sl_first={sl_first} ({sl_first/n_tot*100:.0f}%)  timeout={timeouts}")
    print(f"  expectancy:            {exp_r:+.3f} R per trade")
    print(f"  avg MFE (max favorable): {avg_mfe:.2f}%   avg MAE (max adverse): {avg_mae:.2f}%")
    print(f"  direction mix:         {len(shorts)} short / {len(longs)} long")
    if shorts:
        sw = sum(1 for r in shorts if r["out"]["win"]) / len(shorts) * 100
        print(f"  SHORT win rate:        {sw:.1f}%  ({sum(1 for r in shorts if r['out']['win'])}/{len(shorts)})")
    if longs:
        lw = sum(1 for r in longs if r["out"]["win"]) / len(longs) * 100
        print(f"  LONG win rate:         {lw:.1f}%  ({sum(1 for r in longs if r['out']['win'])}/{len(longs)})")
    # by score tier
    p("BY SCORE TIER")
    for lo, hi, name in [(6, 6, "score 6"), (7, 7, "score 7"), (8, 99, "score 8+")]:
        tier = [r for r in results if lo <= abs(r["score"]) <= hi]
        if tier:
            tw = sum(1 for r in tier if r["out"]["win"]) / len(tier) * 100
            print(f"  {name}: {tw:.1f}% win ({len(tier)} signals)")
    # save for comparison
    import json
    with open("baseline_results.json", "w") as f:
        json.dump({"n": n_tot, "win_rate": wins/n_tot*100, "expectancy_r": exp_r,
                   "short_n": len(shorts), "long_n": len(longs),
                   "per_signal": [{"id": r["id"], "ticker": r["ticker"], "dir": r["direction"],
                                   "score": r["score"], "win": r["out"]["win"],
                                   "result": r["out"]["result"]} for r in results]}, f, indent=2)
    print("\nwrote baseline_results.json")

if __name__ == "__main__":
    run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
