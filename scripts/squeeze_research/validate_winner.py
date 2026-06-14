"""Validate an arbitrary config (e.g. the sweep winner) across multiple windows.
Usage: edit WINNER below with the sweep's top config, then run."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


# Sweep winner (beats baseline on profit AND drawdown on the original week):
WINNER_OVERRIDES = {
    "leverage": 7,
    "capital_pct": 22,
    "max_trades": 4,
    "max_drawdown_pct": 100,
    "target_goal_value": 12,
}

WINDOWS = [
    ("orig 6/04-6/11", "2026-06-04T18:30:00Z", "2026-06-11T06:07:00Z"),
    ("full 6/04-6/13", "2026-06-04T18:30:00Z", "2026-06-13T03:00:00Z"),
    ("oos  6/08-6/13", "2026-06-08T00:00:00Z", "2026-06-13T03:00:00Z"),
    ("oos  6/09-6/13", "2026-06-09T00:00:00Z", "2026-06-13T03:00:00Z"),
]


async def run_win(svc, start, end, overrides):
    cfg = dict(BASE_CONFIG)
    cfg.update(overrides)
    cfg["date_range_start"] = _dt(start)
    cfg["date_range_end"] = _dt(end)
    return await run_one(svc, cfg, None)


async def main():
    svc, db = await build_service()
    try:
        print_header()
        for name, s, e in WINDOWS:
            base = await run_win(svc, s, e, {})
            win = await run_win(svc, s, e, WINNER_OVERRIDES)
            print_row(summarize(base, f"{name} BASE"))
            print_row(summarize(win, f"{name} WINNER"))
            print("  " + "-" * 102)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
