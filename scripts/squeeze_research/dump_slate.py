"""Dump the per-scan candidate slate + which signals were picked, using the REAL
loaded signals (via the engine hook). Read-only: the hook returns None so the
pristine baseline runs, but it records the signals it was handed per scan.

This answers: at selection time, what did each scan offer, what got picked
(top-3 by abs(score)), and were the squeeze symbols distinguishable then?
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, run_one, summarize,
)

# squeeze symbols we want to trace
SQUEEZE = {"SAHARAUSDT", "TSTBSCUSDT", "POLYXUSDT"}

_CAPTURE: dict[str, Any] = {"scans": [], "signal_fields": None}


def capture_hook(config, signals, klines):
    # group by scan, record the candidate slate exactly as the engine sees it
    scans = defaultdict(list)
    for s in signals:
        scans[s["scan_id"]].append(s)
    if signals and _CAPTURE["signal_fields"] is None:
        _CAPTURE["signal_fields"] = sorted(signals[0].keys())
    for sid, sigs in scans.items():
        # rank by abs(score) desc to mirror batch selection
        ranked = sorted(sigs, key=lambda s: abs(s.get("score", 0)), reverse=True)
        _CAPTURE["scans"].append({
            "scan_id": sid,
            "time": str(sigs[0].get("signal_time")),
            "n": len(sigs),
            "ranked": [
                {
                    "ticker": s.get("ticker"),
                    "score": s.get("score"),
                    "direction": s.get("direction"),
                    "confidence": s.get("confidence"),
                    "is_squeeze": (s.get("ticker", "") if s.get("ticker", "").endswith("USDT")
                                   else s.get("ticker", "") + "USDT") in SQUEEZE,
                }
                for s in ranked
            ],
        })
    return None  # pristine


async def main() -> None:
    svc, db = await build_service()
    try:
        row = await run_one(svc, BASE_CONFIG, capture_hook)
        print("signal fields available at selection time:")
        print("  ", _CAPTURE["signal_fields"])
        print(f"\ntotal scans captured: {len(_CAPTURE['scans'])}")
        # show only scans that contained a squeeze symbol
        print("\n=== scans containing a squeeze symbol (rank shown; [P]=top-3 pick) ===")
        for sc in sorted(_CAPTURE["scans"], key=lambda x: x["time"]):
            tickers_sq = [r for r in sc["ranked"] if r["is_squeeze"]]
            if not tickers_sq:
                continue
            print(f"\nscan {sc['scan_id'][:8]} @ {sc['time']}  ({sc['n']} candidates)")
            for i, r in enumerate(sc["ranked"][:12]):
                pick = "[P]" if i < 3 else "   "
                star = "  <== SQUEEZE" if r["is_squeeze"] else ""
                print(f"  {pick} #{i+1:<2} {r['ticker']:<13} score={r['score']:>5} "
                      f"{r['direction']:<5} {r['confidence']:<8}{star}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
