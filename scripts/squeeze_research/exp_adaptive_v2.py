"""Adaptive profit target v2 — EXTENSION-BIASED.

Lesson from v1: closing early cut winners and slashed profit. v2 is biased to
HOLD: default behaviour equals baseline (+15% flush). We only DEVIATE to extend
when the open book shows confirmed favorable momentum, and we only close-early
after we've extended well past 15% and price clearly rolls over.

Momentum signal (no look-ahead): for each open position, compare the current mark
to the mark `lookback` candles ago using the engine's own kline series; a position
is "favorable" if it's moving in the position's direction (short -> price falling).
Book is favorable if the net favorable fraction >= conf.

At the current target:
  - book favorable  -> raise target by `step` (hold, let it run)
  - book NOT favorable -> let the kernel close at the current target (= baseline at
    first step; or lock in the extended gain at a later step)
Give-back stop only active once target has been raised at least once, and only ever
closes ABOVE base_target (never earlier than baseline).
"""
from __future__ import annotations

import asyncio
from typing import Any

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)
from backend.services.trading_rules import compute_unrealized_pnl

_ENGINE = harness.BacktestEngine
_ORIG_CORE = _ENGINE._eval_equity_core


def _mark_before(symbol_klines, ts, back):
    """Close `back` candles before the candle at/just-before ts (no look-ahead)."""
    idx = None
    for i, k in enumerate(symbol_klines):
        if k["open_time"] <= ts:
            idx = i
        else:
            break
    if idx is None:
        return None
    j = idx - back
    if j < 0:
        return None
    return symbol_klines[j]["close"]


def install_adaptive(
    base_target=15.0, step=5.0, ceiling=80.0, conf=0.6,
    lookback=3, giveback_frac=0.40,
    klines_ref: dict | None = None,
):
    ladder: dict[Any, dict[str, float]] = {}

    def patched_core(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time=None):
        if (
            config.get("target_goal_type") != "profit_pct"
            or not config.get("target_goal_value")
            or state.cycle_start_equity <= 0
            or not state.open_positions
        ):
            return _ORIG_CORE(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time)

        ref = state.cycle_start_equity
        total_upnl = 0.0
        for pos in state.open_positions:
            price = latest_prices.get(pos.symbol, pos.entry_price)
            rentry = pos.equity_ref_entry or pos.entry_price
            total_upnl += compute_unrealized_pnl(rentry, price, pos.qty, pos.side)
        equity = state.wallet_balance + total_upnl
        rise_pct = (equity - ref) / ref * 100.0

        key = state.cycle_start_time or id(state)
        st = ladder.get(key)
        if st is None or st["ref"] != ref:
            st = {"ref": ref, "target": base_target, "peak": rise_pct, "raised": 0.0}
            ladder[key] = st
        if rise_pct > st["peak"]:
            st["peak"] = rise_pct

        eff_target = st["target"]

        if rise_pct >= st["target"]:
            # measure book momentum from klines (no look-ahead)
            fav = 0
            tot = 0
            kl = klines_ref or {}
            for pos in state.open_positions:
                sk = kl.get(pos.symbol) or []
                past = _mark_before(sk, candle_time, lookback)
                now = latest_prices.get(pos.symbol, pos.entry_price)
                if past is None or past <= 0:
                    continue
                tot += 1
                chg = (now - past) / past
                # favorable = moving in our direction
                if (pos.side == "Sell" and chg < 0) or (pos.side == "Buy" and chg > 0):
                    fav += 1
            favorable = tot > 0 and (fav / tot) >= conf
            if favorable and st["target"] < ceiling:
                st["target"] = min(ceiling, st["target"] + step)
                st["raised"] += 1
                eff_target = st["target"]
            # else: not favorable -> close at current target (kernel fires)

        # give-back: only after we've raised at least once; never below base_target
        if st["raised"] >= 1 and st["peak"] > base_target:
            gb = (st["peak"] - base_target) * giveback_frac
            if rise_pct <= st["peak"] - gb:
                eff_target = min(eff_target, max(base_target, rise_pct))

        if eff_target != config.get("target_goal_value"):
            cfg = dict(config); cfg["target_goal_value"] = eff_target
            res = _ORIG_CORE(self, cfg, state, latest_prices, candle_time, fee_rate, candles_at_time)
        else:
            res = _ORIG_CORE(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time)
        if state.cycle_start_equity <= 0:
            ladder.pop(key, None)
        return res

    _ENGINE._eval_equity_core = patched_core


def remove_adaptive():
    _ENGINE._eval_equity_core = _ORIG_CORE


# capture klines via the run hook so the momentum measure uses the SAME series the
# engine simulates on.
_KL: dict[str, Any] = {"klines": None}


def _capture_klines_hook(config, signals, klines):
    _KL["klines"] = klines
    return None


async def run_adaptive(svc, **kw):
    # first prime klines with a pristine run capture, then install adaptive using them
    await run_one(svc, BASE_CONFIG, _capture_klines_hook)
    install_adaptive(klines_ref=_KL["klines"], **kw)
    try:
        return await run_one(svc, BASE_CONFIG, None)
    finally:
        remove_adaptive()


async def main():
    svc, db = await build_service()
    try:
        print_header()
        print_row(summarize(await run_one(svc, BASE_CONFIG, None), "baseline (fixed 15%)"))
        for step, ceil, conf, gb in [
            (5, 80, 0.6, 0.40), (10, 80, 0.6, 0.40), (5, 60, 0.5, 0.50),
            (10, 100, 0.7, 0.40), (15, 100, 0.6, 0.40), (5, 50, 0.6, 0.30),
        ]:
            row = await run_adaptive(svc, step=step, ceiling=ceil, conf=conf, giveback_frac=gb)
            print_row(summarize(row, f"adapt s{step} c{ceil} cf{conf} gb{gb}"))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
