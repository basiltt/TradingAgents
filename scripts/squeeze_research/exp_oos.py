"""Out-of-sample robustness: does vol-sizing (pivot 0.75 / min 0.70) help on
windows OTHER than the original drawdown week? If it only helps 6/4-6/11 it's
curve-fit; if it holds across windows it's a real effect.

Runs baseline vs vol-sizing on several date ranges via the REAL engine.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)
from scripts.squeeze_research.exp_vol_sizing import install_vol_sizing, remove_vol_sizing


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


WINDOWS = [
    ("orig 6/04-6/11", "2026-06-04T18:30:00Z", "2026-06-11T06:07:00Z"),
    ("full 6/04-6/13", "2026-06-04T18:30:00Z", "2026-06-13T03:00:00Z"),
    ("oos  6/08-6/13", "2026-06-08T00:00:00Z", "2026-06-13T03:00:00Z"),
    ("oos  6/09-6/13", "2026-06-09T00:00:00Z", "2026-06-13T03:00:00Z"),
]


async def run_win(svc, start, end, sizing):
    cfg = dict(BASE_CONFIG)
    cfg["date_range_start"] = _dt(start)
    cfg["date_range_end"] = _dt(end)
    if sizing:
        install_vol_sizing(0.75, 0.70, sides=("sell",))
    try:
        return await run_one(svc, cfg, None)
    finally:
        if sizing:
            remove_vol_sizing()


async def main() -> None:
    svc, db = await build_service()
    try:
        print_header()
        for name, s, e in WINDOWS:
            base = await run_win(svc, s, e, False)
            vs = await run_win(svc, s, e, True)
            print_row(summarize(base, f"{name} BASE"))
            print_row(summarize(vs, f"{name} VOLSIZE"))
            print("  " + "-" * 102)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
