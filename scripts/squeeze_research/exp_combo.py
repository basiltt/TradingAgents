"""Combine the two interventions that each helped, and probe the path-fork
amplifier (target_goal_value / EQUITY_RISE flush).

We test, in the REAL engine:
  A. vol-sizing on a LEVERAGE-7 base (combine the two robust levers)
  B. vol-sizing with the squeeze names sized down only MILDLY (min 0.6) so the
     path forks less
  C. leverage 7 + vol-sizing + a wider equity-rise target to reduce path forks

Goal: find a combo that beats BOTH baseline-DD AND leverage-7 net profit.
"""
from __future__ import annotations

import asyncio

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)
from scripts.squeeze_research.exp_vol_sizing import install_vol_sizing, remove_vol_sizing


async def run_combo(svc, cfg, pivot=None, min_frac=None):
    if pivot is not None:
        install_vol_sizing(pivot, min_frac, sides=("sell",))
    try:
        return await run_one(svc, cfg, None)
    finally:
        if pivot is not None:
            remove_vol_sizing()


async def main() -> None:
    svc, db = await build_service()
    try:
        print_header()
        base = await run_one(svc, BASE_CONFIG, None)
        print_row(summarize(base, "baseline (lev8)"))

        # reference: leverage 7 alone (the current best robust)
        cfg_l7 = dict(BASE_CONFIG); cfg_l7["leverage"] = 7
        print_row(summarize(await run_one(svc, cfg_l7, None), "lev7 alone"))

        # A. vol-sizing on lev-7 base
        for pivot, mf in [(0.75, 0.33), (0.80, 0.5), (0.70, 0.5)]:
            row = await run_combo(svc, cfg_l7, pivot, mf)
            print_row(summarize(row, f"lev7 + volsize {pivot}/{mf}"))

        # B. vol-sizing on lev-8 base, MILD shrink (min 0.6 / 0.7)
        for pivot, mf in [(0.75, 0.6), (0.80, 0.7), (0.85, 0.6)]:
            row = await run_combo(svc, BASE_CONFIG, pivot, mf)
            print_row(summarize(row, f"lev8 + volsize {pivot}/{mf}"))

        # C. lev7 + vol-sizing + wider equity-rise target (less path-fork)
        cfg_l7_wide = dict(cfg_l7); cfg_l7_wide["target_goal_value"] = 20
        print_row(summarize(await run_combo(svc, cfg_l7_wide, 0.75, 0.5),
                            "lev7 + vol .75/.5 + tgt20"))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
