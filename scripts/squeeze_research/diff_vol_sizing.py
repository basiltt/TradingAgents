"""Diff baseline vs the best vol-sizing variant: did it KEEP the same entries
(just smaller) or did the path shift? Captures actual trades from the engine."""
from __future__ import annotations

import asyncio
import copy

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import BASE_CONFIG, build_service, run_one
from scripts.squeeze_research.exp_vol_sizing import install_vol_sizing, remove_vol_sizing


async def run_capture(svc, with_sizing):
    if with_sizing:
        install_vol_sizing(0.75, 0.33)
    try:
        await run_one(svc, BASE_CONFIG, None)
        res = harness.LAST_RESULT["result"]
        return copy.deepcopy(res.trades if res else [])
    finally:
        if with_sizing:
            remove_vol_sizing()


def k(t):
    return (t.get("symbol"), str(t.get("entry_time"))[:16])


async def main():
    svc, db = await build_service()
    try:
        base = await run_capture(svc, False)
        vs = await run_capture(svc, True)
        bk = {k(t): t for t in base}
        vk = {k(t): t for t in vs}
        common = set(bk) & set(vk)
        only_b = set(bk) - set(vk)
        only_v = set(vk) - set(bk)
        print(f"baseline trades: {len(base)}   vol-sizing trades: {len(vs)}")
        print(f"shared entries (same symbol+time): {len(common)}")
        print(f"only in baseline: {len(only_b)}   only in vol-sizing: {len(only_v)}")
        # for shared entries, show how PnL changed (should shrink for high-vol)
        print("\nshared SAHARA/TSTBSC/POLYX (the squeezes) — size effect:")
        for key in sorted(common, key=lambda x: x[1]):
            if key[0] in ("SAHARAUSDT", "TSTBSCUSDT", "POLYXUSDT"):
                b, v = bk[key], vk[key]
                print(f"  {key[0]:<12} @ {key[1]}  base_pnl={b.get('pnl'):>8.2f}  "
                      f"volsize_pnl={v.get('pnl'):>8.2f}  (qty {b.get('qty'):.4g} -> {v.get('qty'):.4g})")
        print(f"\nentries DROPPED by vol-sizing path-shift ({len(only_b)}):")
        for key in sorted(only_b, key=lambda x: x[1])[:15]:
            print(f"  -{key[0]:<12} @ {key[1]}  base_pnl={bk[key].get('pnl'):>8.2f}")
        print(f"\nNEW entries from vol-sizing path-shift ({len(only_v)}):")
        for key in sorted(only_v, key=lambda x: x[1])[:15]:
            print(f"  +{key[0]:<12} @ {key[1]}  pnl={vk[key].get('pnl'):>8.2f}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
