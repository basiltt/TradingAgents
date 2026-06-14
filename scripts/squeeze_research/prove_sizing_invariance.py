"""Prove that a SIZING change (leverage / capital_pct) preserves the exact trade
SEQUENCE (same symbols, same entry/exit times, same close reasons) and only
scales magnitudes — unlike entry filters, which reshuffle the whole path.

If the symbol+time set is identical between baseline and a sizing variant, the
sizing lever is "path-preserving": it cannot introduce NEW squeeze trades, so it
is a SAFE way to cut drawdown. We then sweep to find the efficient frontier.
"""
from __future__ import annotations

import asyncio
import copy

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)


async def run_capture(svc, cfg):
    await run_one(svc, cfg, None)
    res = harness.LAST_RESULT["result"]
    return copy.deepcopy(res.trades if res else [])


def seq(trades):
    # ordered sequence of (symbol, entry_time, exit_time, close_reason)
    return [
        (t.get("symbol"), str(t.get("entry_time"))[:16], str(t.get("exit_time"))[:16],
         t.get("close_reason"))
        for t in sorted(trades, key=lambda t: str(t.get("entry_time")))
    ]


async def main():
    svc, db = await build_service()
    try:
        base = await run_capture(svc, BASE_CONFIG)
        base_seq = seq(base)

        # leverage variants (path-preserving hypothesis)
        for lev in (5, 6, 7):
            cfg = dict(BASE_CONFIG); cfg["leverage"] = lev
            t = await run_capture(svc, cfg)
            same = seq(t) == base_seq
            print(f"leverage {lev}: trade-sequence identical to baseline? {same} "
                  f"({len(t)} vs {len(base)} trades)")
            if not same:
                # show first divergence
                s2 = seq(t)
                for i, (a, b) in enumerate(zip(base_seq, s2)):
                    if a != b:
                        print(f"    first divergence @ #{i}: base={a}  variant={b}")
                        break
        print()
        # capital_pct variants
        for cap in (10, 15, 18):
            cfg = dict(BASE_CONFIG); cfg["capital_pct"] = cap
            t = await run_capture(svc, cfg)
            same = seq(t) == base_seq
            print(f"capital_pct {cap}: trade-sequence identical to baseline? {same} "
                  f"({len(t)} vs {len(base)} trades)")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
