"""Experiment: VOLATILITY-TARGETED POSITION SIZING.

The key realization from the trade-diff proof: every failed approach REMOVED or
SWAPPED trades, which poisons the path (fill_to_max_trades backfill + double_failure
cooloff). This experiment does NOT remove any trade. It keeps the exact same entry
set, count, and selection order — but scales each position's capital_pct by its
pre-entry realized volatility (ATR%), so a squeeze-prone high-vol name like SAHARA
gets a SMALLER bet while calm names keep full size.

Mechanism: monkeypatch BacktestEngine._open_position to override config["capital_pct"]
per-signal based on ATR% computed from candles STRICTLY BEFORE the fill (no
look-ahead). Vol target = baseline capital_pct at a pivot ATR%; above pivot, size
scales down by (pivot / atr); clamped to [min_frac, 1.0] x base. Never scales ABOVE
base, so total deployed margin can only DECREASE (respects the <=97% bound trivially).

This is path-LIGHT (not path-free): smaller positions shift equity slightly, which can
nudge equity-rule close timing — so we still verify in the REAL engine, never on paper.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)

_ENGINE = harness.BacktestEngine
_ORIG_OPEN = _ENGINE._open_position


def _atr_pct_before(symbol_klines, ts, n=14):
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


def install_vol_sizing(pivot: float, min_frac: float, sides=("sell",)) -> None:
    """Patch _open_position to scale capital_pct down for high-ATR signals."""
    base_cap = BASE_CONFIG["capital_pct"]

    def patched_open(self, config, signal, klines, state, current_time, relaxed=False):
        direction = signal.get("direction", "")
        scale = 1.0
        if direction in sides:
            atr = _atr_pct_before(klines.get(signal.get("ticker", ""), []), current_time)
            if atr is not None and atr > pivot:
                scale = max(min_frac, pivot / atr)
        if scale < 1.0:
            # shallow-copy config with a scaled capital_pct just for this open
            cfg = dict(config)
            cfg["capital_pct"] = base_cap * scale
            return _ORIG_OPEN(self, cfg, signal, klines, state, current_time, relaxed)
        return _ORIG_OPEN(self, config, signal, klines, state, current_time, relaxed)

    _ENGINE._open_position = patched_open


def remove_vol_sizing() -> None:
    _ENGINE._open_position = _ORIG_OPEN


async def run_with_sizing(svc, pivot, min_frac):
    install_vol_sizing(pivot, min_frac)
    try:
        return await run_one(svc, BASE_CONFIG, None)
    finally:
        remove_vol_sizing()


async def main() -> None:
    svc, db = await build_service()
    try:
        print_header()
        base = await run_one(svc, BASE_CONFIG, None)
        print_row(summarize(base, "baseline (lev8)"))
        # pivot = ATR% above which we start shrinking. Winners' median ATR ~0.5,
        # p75 ~0.68; squeezes 0.84-0.95. Pivots around 0.55-0.70 shrink the squeezes
        # hardest while barely touching most winners.
        for pivot, min_frac in [
            (0.80, 0.70), (0.80, 0.65), (0.85, 0.70),
            (0.75, 0.70), (0.90, 0.65), (0.80, 0.75),
            (0.85, 0.75), (0.75, 0.75),
        ]:
            row = await run_with_sizing(svc, pivot, min_frac)
            print_row(summarize(row, f"volsize pivot={pivot} min={min_frac}"))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
