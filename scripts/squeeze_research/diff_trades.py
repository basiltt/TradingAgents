"""Why does the vol veto backfire? Compare baseline vs veto ACTUAL trade sets,
captured directly from the engine result (harness.LAST_RESULT)."""
from __future__ import annotations

import asyncio
import copy

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import BASE_CONFIG, build_service, run_one
from scripts.squeeze_research.exp_vol_veto import make_vol_veto_hook


async def run_capture(svc, cfg, hook):
    await run_one(svc, cfg, hook)
    res = harness.LAST_RESULT["result"]
    return copy.deepcopy(res.trades if res else [])


def key(t):
    return (t.get("symbol"), str(t.get("entry_time"))[:16])


def show(trades, label):
    losers = sorted([t for t in trades if (t.get("pnl") or 0) < 0], key=lambda t: t.get("pnl", 0))[:8]
    net = sum(t.get("pnl") or 0 for t in trades)
    print(f"\n=== {label}: {len(trades)} trades, net={net:.2f} ===")
    print("  biggest losers:")
    for t in losers:
        print(f"    {t.get('symbol'):<12} {t.get('side'):<5} pnl={t.get('pnl'):>8.2f} "
              f"({t.get('pnl_pct'):>6.1f}%) {str(t.get('close_reason')):<14} entry={str(t.get('entry_time'))[:16]}")


async def main():
    svc, db = await build_service()
    try:
        base = await run_capture(svc, BASE_CONFIG, None)
        veto = await run_capture(svc, BASE_CONFIG, make_vol_veto_hook(0.80))
        show(base, "BASELINE")
        show(veto, "VOL_VETO 0.80")
        bk = {key(t): t for t in base}
        vk = {key(t): t for t in veto}
        only_base = set(bk) - set(vk)
        only_veto = set(vk) - set(bk)
        print(f"\n=== DIFF: avoided by veto ({len(only_base)}) ===")
        for kk in sorted(only_base, key=lambda x: x[1]):
            t = bk[kk]
            print(f"  -{kk[0]:<12} @ {kk[1]}  pnl={t.get('pnl'):>8.2f} ({t.get('pnl_pct'):>6.1f}%)")
        print(f"\n=== DIFF: NEW trades from veto ({len(only_veto)}) ===")
        for kk in sorted(only_veto, key=lambda x: x[1]):
            t = vk[kk]
            print(f"  +{kk[0]:<12} @ {kk[1]}  pnl={t.get('pnl'):>8.2f} ({t.get('pnl_pct'):>6.1f}%) {t.get('close_reason')}")
        # net effect
        print(f"\n  avoided net: {sum(bk[k].get('pnl') or 0 for k in only_base):.2f}")
        print(f"  new net:     {sum(vk[k].get('pnl') or 0 for k in only_veto):.2f}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
