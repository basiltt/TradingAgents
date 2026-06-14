"""Does book momentum at the +15% crossing PREDICT that holding longer pays?

At each candle where a cycle first crosses +15%, record:
  - book momentum (favorable fraction over `lookback`)
  - what equity rise would have been reachable if we held N more candles
    (the forward MAX rise before the cycle would otherwise end / reverse)

If favorable-momentum crossings have materially higher forward rise than
unfavorable ones, an adaptive hold has edge. If not, holding is a coin flip and
the fixed 15% is already near-optimal.

This is a MEASUREMENT (uses forward candles for analysis ONLY — not a trading
rule), to decide whether the adaptive approach can work at all.
"""
from __future__ import annotations

import asyncio
from typing import Any

from scripts.squeeze_research import harness
from scripts.squeeze_research.harness import BASE_CONFIG, build_service, run_one
from backend.services.trading_rules import compute_unrealized_pnl

_ENGINE = harness.BacktestEngine
_ORIG_CORE = _ENGINE._eval_equity_core
_KL: dict[str, Any] = {"klines": None}
_OBS: list[dict] = []


def _mark_before(sk, ts, back):
    idx = None
    for i, k in enumerate(sk):
        if k["open_time"] <= ts:
            idx = i
        else:
            break
    if idx is None or idx - back < 0:
        return None
    return sk[idx - back]["close"]


def _mark_after_max_rise(state, ref, ts, klines, horizon=24):
    """Best (max) cycle rise% achievable over the next `horizon` candles if we held
    the CURRENT book frozen (no new entries) — an upper bound on hold benefit."""
    # collect future timestamps from the open symbols
    syms = [p.symbol for p in state.open_positions]
    # build per-symbol forward closes
    fut_times = set()
    per = {}
    for p in state.open_positions:
        sk = klines.get(p.symbol) or []
        seq = [(k["open_time"], k["close"]) for k in sk if k["open_time"] > ts][:horizon]
        per[p.symbol] = seq
        for t, _ in seq:
            fut_times.add(t)
    if not fut_times:
        return None
    # mark-forward each symbol; compute equity at each future time
    best = -1e9
    last_close = {p.symbol: state for p in state.open_positions}
    marks = {}
    for p in state.open_positions:
        marks[p.symbol] = (p.equity_ref_entry or p.entry_price)
    # seed marks with current
    for p in state.open_positions:
        sk = klines.get(p.symbol) or []
        cur = None
        for k in sk:
            if k["open_time"] <= ts:
                cur = k["close"]
            else:
                break
        if cur:
            marks[p.symbol] = cur
    idxs = {p.symbol: 0 for p in state.open_positions}
    for t in sorted(fut_times):
        for p in state.open_positions:
            seq = per[p.symbol]
            while idxs[p.symbol] < len(seq) and seq[idxs[p.symbol]][0] <= t:
                marks[p.symbol] = seq[idxs[p.symbol]][1]
                idxs[p.symbol] += 1
        upnl = 0.0
        for p in state.open_positions:
            upnl += compute_unrealized_pnl(p.equity_ref_entry or p.entry_price, marks[p.symbol], p.qty, p.side)
        eq = state.wallet_balance + upnl
        rise = (eq - ref) / ref * 100.0
        best = max(best, rise)
    return best


def observe_core(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time=None):
    if (config.get("target_goal_type") == "profit_pct" and config.get("target_goal_value")
            and state.cycle_start_equity > 0 and state.open_positions):
        ref = state.cycle_start_equity
        upnl = sum(compute_unrealized_pnl(p.equity_ref_entry or p.entry_price,
                   latest_prices.get(p.symbol, p.entry_price), p.qty, p.side)
                   for p in state.open_positions)
        rise = (state.wallet_balance + upnl - ref) / ref * 100.0
        tgt = config.get("target_goal_value")
        # record only the FIRST crossing of the target in this cycle
        if rise >= tgt and not getattr(state, "_obs_marked", False):
            kl = _KL["klines"] or {}
            fav = tot = 0
            for p in state.open_positions:
                past = _mark_before(kl.get(p.symbol) or [], candle_time, 3)
                now = latest_prices.get(p.symbol, p.entry_price)
                if past and past > 0:
                    tot += 1
                    chg = (now - past) / past
                    if (p.side == "Sell" and chg < 0) or (p.side == "Buy" and chg > 0):
                        fav += 1
            fwd = _mark_after_max_rise(state, ref, candle_time, kl, horizon=24)
            _OBS.append({
                "rise_at_cross": rise,
                "fav_frac": (fav / tot) if tot else None,
                "fwd_max_rise": fwd,
                "hold_benefit": (fwd - rise) if fwd is not None else None,
            })
            state._obs_marked = True
        if rise < tgt and getattr(state, "_obs_marked", False):
            state._obs_marked = False
    return _ORIG_CORE(self, config, state, latest_prices, candle_time, fee_rate, candles_at_time)


def hook(config, signals, klines):
    _KL["klines"] = klines
    return None


async def main():
    svc, db = await build_service()
    try:
        # prime klines
        await run_one(svc, BASE_CONFIG, hook)
        _ENGINE._eval_equity_core = observe_core
        try:
            await run_one(svc, BASE_CONFIG, hook)
        finally:
            _ENGINE._eval_equity_core = _ORIG_CORE
        obs = [o for o in _OBS if o["hold_benefit"] is not None and o["fav_frac"] is not None]
        print(f"observed {len(obs)} cycle +15% crossings\n")
        fav = [o for o in obs if o["fav_frac"] >= 0.6]
        unf = [o for o in obs if o["fav_frac"] < 0.6]
        def avg(g, k): return sum(o[k] for o in g) / len(g) if g else float('nan')
        print(f"FAVORABLE momentum (fav>=0.6): n={len(fav)}  "
              f"avg hold_benefit={avg(fav,'hold_benefit'):.2f}%  "
              f"avg fwd_max_rise={avg(fav,'fwd_max_rise'):.2f}%")
        print(f"UNFAVORABLE momentum (fav<0.6): n={len(unf)}  "
              f"avg hold_benefit={avg(unf,'hold_benefit'):.2f}%  "
              f"avg fwd_max_rise={avg(unf,'fwd_max_rise'):.2f}%")
        print("\nIf FAVORABLE hold_benefit >> UNFAVORABLE, adaptive hold has edge.")
        print("\nper-crossing detail:")
        for o in obs:
            print(f"  rise@cross={o['rise_at_cross']:.1f}%  fav={o['fav_frac']:.2f}  "
                  f"fwd_max={o['fwd_max_rise']:.1f}%  hold_benefit={o['hold_benefit']:+.1f}%")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
