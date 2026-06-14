"""Deep-dive the full-window (6/04-6/13) baseline vs vol-sizing: explain the
DD and profit gap with actual trades + equity milestones."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import BASE_CONFIG, build_service, run_one
from scripts.squeeze_research.exp_vol_sizing import install_vol_sizing, remove_vol_sizing


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


async def run_full(svc, sizing):
    cfg = dict(BASE_CONFIG)
    cfg["date_range_start"] = _dt("2026-06-04T18:30:00Z")
    cfg["date_range_end"] = _dt("2026-06-13T03:00:00Z")
    if sizing:
        install_vol_sizing(0.75, 0.70, sides=("sell",))
    try:
        row = await run_one(svc, cfg, None)
        res = harness.LAST_RESULT["result"]
        return row, copy.deepcopy(res.trades if res else [])
    finally:
        if sizing:
            remove_vol_sizing()


def metrics(row):
    return ((row or {}).get("results") or {}).get("metrics") or {}


def dd_trough(row):
    """Find the equity-curve point of max drawdown."""
    eq = ((row or {}).get("results") or {}).get("equity_curve") or []
    worst = min(eq, key=lambda p: p.get("drawdown_pct", 0)) if eq else {}
    peak = max(eq, key=lambda p: p.get("equity", 0)) if eq else {}
    return worst, peak


async def main():
    svc, db = await build_service()
    try:
        b_row, b_tr = await run_full(svc, False)
        v_row, v_tr = await run_full(svc, True)
        bm, vm = metrics(b_row), metrics(v_row)

        print("=== FULL WINDOW 6/04 18:30 -> 6/13 03:00 ===\n")
        cols = ["net_profit", "net_profit_pct", "max_dd_pct", "max_dd_usd",
                "win_rate", "total_trades", "largest_loss", "sharpe",
                "profit_factor", "final_equity"]
        print(f"{'metric':<18}{'BASELINE':>16}{'VOL-SIZING':>16}")
        for c in cols:
            bv, vv = bm.get(c), vm.get(c)
            fb = f"{bv:.2f}" if isinstance(bv, (int, float)) else str(bv)
            fv = f"{vv:.2f}" if isinstance(vv, (int, float)) else str(vv)
            print(f"{c:<18}{fb:>16}{fv:>16}")

        bw, bp = dd_trough(b_row)
        vw, vp = dd_trough(v_row)
        print(f"\nmax-DD trough:")
        print(f"  baseline : {bw.get('drawdown_pct'):.2f}% at {bw.get('ts')}  equity={bw.get('equity'):.2f}")
        print(f"  volsize  : {vw.get('drawdown_pct'):.2f}% at {vw.get('ts')}  equity={vw.get('equity'):.2f}")

        # the 3 squeeze trades in each
        print("\nsqueeze trades (size effect):")
        bk = {(t['symbol'], str(t['entry_time'])[:16]): t for t in b_tr}
        vk = {(t['symbol'], str(t['entry_time'])[:16]): t for t in v_tr}
        for key in sorted(set(bk) & set(vk)):
            if key[0] in ("SAHARAUSDT", "TSTBSCUSDT", "POLYXUSDT"):
                print(f"  {key[0]:<12} @ {key[1]}  base={bk[key]['pnl']:>8.2f}  vol={vk[key]['pnl']:>8.2f}")

        # what trades differ
        only_b = set(bk) - set(vk)
        only_v = set(vk) - set(bk)
        net_b = sum(bk[k]['pnl'] for k in only_b)
        net_v = sum(vk[k]['pnl'] for k in only_v)
        print(f"\npath fork: baseline-only {len(only_b)} trades (net {net_b:+.2f}), "
              f"volsize-only {len(only_v)} trades (net {net_v:+.2f})")
        # biggest baseline-only winners that vol-sizing missed
        print("biggest winners vol-sizing's path MISSED:")
        for k in sorted(only_b, key=lambda x: -bk[x]['pnl'])[:6]:
            print(f"  -{k[0]:<12} @ {k[1]}  {bk[k]['pnl']:+.2f}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
