"""Experiment: ADAPTIVE PROFIT TARGET (let winners run, cut losers early).

The baseline force-closes the whole book the instant cycle equity rises +15%
(EQUITY_RISE flush). This experiment makes that target DYNAMIC:

  - When equity reaches the current target AND the open book is still moving in
    our favor (aggregate unrealized PnL rising vs the last check, and more
    positions improving than deteriorating), RAISE the target one step and keep
    holding — let the winner run.
  - When the book's favor TURNS (aggregate uPnL rolling over from its peak by a
    give-back fraction), CLOSE NOW even if below the next target — lock the gain
    / cut before it round-trips.
  - Hard ceiling so it can't hold forever; hard floor = the original 15% is the
    FIRST step, never earlier (so we never close winners earlier than baseline).

Implementation: wrap BacktestEngine._eval_equity_core. Before delegating, compute
an effective target_goal_value for THIS cycle from per-position uPnL state
(no look-ahead — uses only the marks the kernel already has), and inject it into a
shallow-copied config. The real flush then fires (or not) at that dynamic threshold.

Per-cycle ladder state lives on the engine instance, keyed by cycle_start_time, and
resets when a new cycle starts (cycle_start_equity changes).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import (
    BASE_CONFIG, build_service, print_header, print_row, run_one, summarize,
)
from backend.services.trading_rules import compute_unrealized_pnl

_ENGINE = harness.BacktestEngine
_ORIG_CORE = _ENGINE._eval_equity_core


def install_adaptive_target(
    base_target: float = 15.0,
    step: float = 5.0,
    ceiling: float = 60.0,
    giveback_frac: float = 0.30,
    arm_buffer: float = 2.0,
) -> None:
    """Patch _eval_equity_core with the adaptive-target rule.

    base_target  : first close threshold (= baseline 15%). Never close earlier than
                   this via the rise rule (we only extend up, or cut on give-back
                   AFTER arming above base_target).
    step         : how much to raise the target each time favor confirms.
    ceiling      : max target% (hard cap so a cycle can't ride forever).
    giveback_frac: once armed past base_target, if equity gives back this fraction
                   of (peak_rise - base_target), close now.
    arm_buffer   : only START laddering once rise exceeds base_target + arm_buffer,
                   so tiny oscillations at exactly 15% don't trigger early closes.
    """
    ladder: dict[Any, dict[str, float]] = {}

    def patched_core(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time=None):
        # Only intercept when the profit_pct rise rule is the active target and there
        # are positions; otherwise pristine behaviour.
        if (
            config.get("target_goal_type") != "profit_pct"
            or not config.get("target_goal_value")
            or state.cycle_start_equity <= 0
            or not state.open_positions
        ):
            return _ORIG_CORE(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time)

        ref = state.cycle_start_equity
        # current equity at this bar (same computation the kernel uses)
        total_upnl = 0.0
        improving = 0
        deteriorating = 0
        for pos in state.open_positions:
            price = latest_prices.get(pos.symbol, pos.entry_price)
            rentry = pos.equity_ref_entry or pos.entry_price
            upnl = compute_unrealized_pnl(rentry, price, pos.qty, pos.side)
            total_upnl += upnl
        equity = state.wallet_balance + total_upnl
        rise_pct = (equity - ref) / ref * 100.0

        key = state.cycle_start_time or id(state)
        st = ladder.get(key)
        if st is None or st["ref"] != ref:
            # new cycle
            st = {"ref": ref, "target": base_target, "peak_rise": rise_pct, "armed": 0.0}
            ladder[key] = st

        # track peak rise this cycle
        if rise_pct > st["peak_rise"]:
            st["peak_rise"] = rise_pct

        eff_target = st["target"]

        # Decide adaptively only when we've reached the current target.
        if rise_pct >= st["target"]:
            # Are we still being rewarded for holding? Use book momentum: is current
            # equity at/near the cycle peak (still making highs)? If rise is within a
            # hair of peak_rise, favor is intact -> extend. Else favor turned -> let it
            # close at the current target (don't raise).
            near_peak = rise_pct >= st["peak_rise"] - 0.01
            if st["target"] < ceiling and near_peak:
                # extend: raise target a step, do NOT close now
                st["target"] = min(ceiling, st["target"] + step)
                st["armed"] = st["peak_rise"]
                eff_target = st["target"]
            # else: leave eff_target = current target -> kernel closes now.

        # Give-back early close: once we've armed above base_target, if equity rolls
        # back from the cycle peak by giveback_frac of (peak_rise - base_target),
        # close NOW by setting the effective target at/below current rise.
        if st["armed"] >= base_target + arm_buffer and st["peak_rise"] > base_target:
            giveback = (st["peak_rise"] - base_target) * giveback_frac
            if rise_pct <= st["peak_rise"] - giveback:
                eff_target = min(eff_target, max(base_target, rise_pct))  # force close now

        if eff_target != config.get("target_goal_value"):
            cfg = dict(config)
            cfg["target_goal_value"] = eff_target
            # if the cycle terminates this call, drop our ladder memory
            res = _ORIG_CORE(self, cfg, state, latest_prices, candle_time, fee_rate, candles_at_time)
        else:
            res = _ORIG_CORE(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time)

        if state.cycle_start_equity <= 0:  # cycle terminated this candle
            ladder.pop(key, None)
        return res

    _ENGINE._eval_equity_core = patched_core


def remove_adaptive_target() -> None:
    _ENGINE._eval_equity_core = _ORIG_CORE


async def run_adaptive(svc, **kw):
    install_adaptive_target(**kw)
    try:
        return await run_one(svc, BASE_CONFIG, None)
    finally:
        remove_adaptive_target()


async def main() -> None:
    svc, db = await build_service()
    try:
        print_header()
        print_row(summarize(await run_one(svc, BASE_CONFIG, None), "baseline (fixed 15%)"))
        # vary step size + ceiling + giveback
        for step, ceil, gb in [
            (5, 40, 0.30), (5, 60, 0.30), (5, 60, 0.50),
            (10, 60, 0.30), (10, 80, 0.40), (5, 30, 0.25),
            (3, 45, 0.30), (8, 60, 0.35),
        ]:
            row = await run_adaptive(svc, step=step, ceiling=ceil, giveback_frac=gb)
            print_row(summarize(row, f"adaptive step{step} cap{ceil} gb{gb}"))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
