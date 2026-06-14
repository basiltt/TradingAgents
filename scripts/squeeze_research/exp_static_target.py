"""Simplest possible test of the 'let winners run' edge: just RAISE the fixed
target_goal_value (no momentum logic, no early close). The hold-edge measurement
showed +6% avg forward benefit at the +15% crossing, positive in 25/26 cases.

If a higher static target converts that forward edge into realized profit, the
edge is real and capturable. If it doesn't (path-fork / squeeze-on-hold eats it),
then the fixed 15% is already near-optimal and 'let it run' can't beat it here.

Pure config change — no engine patch. Tests target 15,18,20,25,30,40 and also
'no flush' (target so high it never fires; cycle ends only on other rules).
"""
from __future__ import annotations

import asyncio

from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)


async def main():
    svc, db = await build_service()
    try:
        print_header()
        for tgt in (15, 18, 20, 22, 25, 30, 40, 1000):
            cfg = dict(BASE_CONFIG)
            cfg["target_goal_value"] = tgt
            row = await run_one(svc, cfg, None)
            label = "baseline (15)" if tgt == 15 else (f"target {tgt}" if tgt < 1000 else "no rise-flush (1000)")
            print_row(summarize(row, label))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
