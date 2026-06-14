"""Experiment: selection-time volatility veto.

Hypothesis: the 3 squeeze losers all sit in a high pre-entry realized-volatility
band (ATR% over the 14 prior 5m bars in 0.84-0.95), while ~75% of winners sit
below 0.68. Dropping candidates whose pre-entry ATR% exceeds a threshold BEFORE
ranking lets fill_to_max_trades backfill with the next, calmer candidate — so the
book stays full (avoiding the capital-reshuffle backfire we saw from blacklisting).

This hook removes vetoed signals from the list the engine ranks/opens, computing
ATR% only from candles STRICTLY BEFORE each scan's selection instant (no
look-ahead). Everything else (ranking, fill, close rules) is the untouched engine.

Run:  python -m scripts.squeeze_research.exp_vol_veto            # sweep
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Optional

from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)

SQUEEZE = {"SAHARAUSDT", "TSTBSCUSDT", "POLYXUSDT"}


def _to_symbol(t: str) -> str:
    return t if t.endswith("USDT") else f"{t}USDT"


def _atr_pct_before(symbol_klines, ts, n=14):
    """ATR% over the n 5m bars strictly before ts. None if insufficient history."""
    pre = []
    for k in symbol_klines:
        if k["open_time"] < ts:
            pre.append(k)
        else:
            break
    if len(pre) < n + 1:
        return None
    last = pre[-1]["close"]
    if last <= 0:
        return None
    trs = []
    for i in range(1, n + 1):
        h, l, pc = pre[-i]["high"], pre[-i]["low"], pre[-i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return (sum(trs) / len(trs)) / last * 100


def make_vol_veto_hook(threshold: float, sides=("sell",)) -> Any:
    """Return a hook that drops candidates with pre-entry ATR% >= threshold.

    Only applies to the given signal sides (default: shorts only — squeeze risk is
    a short phenomenon; longs are left untouched). Hold signals pass through.
    """
    def hook(config, signals, klines):
        scans = defaultdict(list)
        for s in signals:
            scans[s["scan_id"]].append(s)
        kept = []
        for sid, sigs in scans.items():
            ts = sigs[0].get("signal_time")
            for s in sigs:
                direction = s.get("direction", "")
                if direction in sides:
                    atr = _atr_pct_before(klines.get(s.get("ticker", ""), []), ts)
                    if atr is not None and atr >= threshold:
                        continue  # veto this high-vol short
                kept.append(s)
        return config, kept
    return hook


async def main() -> None:
    svc, db = await build_service()
    try:
        print_header()
        base = await run_one(svc, BASE_CONFIG, None)
        print_row(summarize(base, "baseline"))
        for thr in (1.00, 0.90, 0.80, 0.75, 0.70, 0.60):
            row = await run_one(svc, BASE_CONFIG, make_vol_veto_hook(thr))
            print_row(summarize(row, f"vol_veto shorts>={thr:.2f}"))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
