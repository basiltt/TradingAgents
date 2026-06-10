"""CLI: replay an account's live selection through BacktestEngine and report parity.

Pins each cycle's actual live-traded (symbol, side) so the engine opens exactly the
symbols live did, then simulates fills/closes/PnL/compounding from cached candles.
Compares the result cycle-by-cycle against the live `trades` oracle.

Usage:
  DATABASE_URL=postgresql://postgres:...@localhost:5432/tradingagents \
  python -m backend.diagnostics.parity.run_parity \
      --account 75aecaa7-0f10-400b-a562-1ddd7ae6cf94 \
      --start 2026-06-04T22:00:00Z --end 2026-06-10T06:00:00Z
"""
from __future__ import annotations
import argparse
import asyncio
import os
from datetime import datetime, timezone, timedelta

from backend.async_persistence import AsyncAnalysisDB
from backend.services.kline_cache_service import KlineCacheService
from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.data_access import ParityDataAccess
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import build_report, format_report, run_cycles_isolated

# Dad - Demo config under test (see plan Reference Facts).
# NOTE: breakeven_timeout_hours is deliberately set to None (disabled) for the
# parity SIM even though the live account config has it at 12h. Verified against the
# entire production DB: NO trade has EVER closed via breakeven (Dad all-time:
# 183 rule_triggered / 68 external / 49 manual_close_all / 0 breakeven; zero
# breakeven closes across ALL accounts). Live's breakeven evaluates account wallet
# PnL on a 60s poll and, in practice, never fired; the deterministic 5m-candle
# engine instead fires it on transient buffer-crossings that live's polling skips,
# capping winners (e.g. HNT live +75.28 vs engine breakeven +22.80). Disabling it
# in the sim removes a divergence with no live counterpart. The production engine is
# untouched — this is a harness-config choice, so the golden suite stays byte-exact.
CONFIG = {
    "leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
    "stop_loss_pct": 100, "max_drawdown_pct": 12, "smart_drawdown_close": True,
    "trailing_profit_pct": 2, "breakeven_timeout_hours": None, "max_trade_duration_hours": 24,
    "min_score": 7, "confidence_filter": "moderate", "signal_sides": "both",
    "execution_mode": "batch", "fill_to_max_trades": True, "skip_if_positions_open": True,
    "adaptive_blacklist_enabled": True, "adaptive_blacklist_min_trades": 5,
    "adaptive_blacklist_max_win_rate": 30, "adaptive_blacklist_lookback_hours": 48,
    "target_goal_type": "profit_pct", "target_goal_value": 15, "max_price_drift_pct": None,
    "max_same_sector": 2, "max_same_direction": 3, "direction": "straight",
    "fee_rate_pct": 0.055, "slippage_bps": 2, "simulation_interval": "5m",
}
# max_price_drift_pct is None (gate OFF) in the parity sim. The drift gate is a
# SELECTION-time filter (reject a signal whose price already ran past the cap before
# entry). The harness PINS live's actual trades, so selection is already decided from
# ground truth — re-applying a selection gate that live demonstrably passed is wrong
# by construction. Concretely it spuriously rejected BLESSUSDT: the engine's 5m
# next-bar-open (0.009015, a transient spike) drifted +5.4% vs analysis, but live
# filled lower (0.008754) with no drift and traded it (a real -66 loss). Leaving the
# gate on makes the sim drop a losing trade live took, biasing the result optimistic.
# Harness-config only; production engine + golden suite untouched.


def _dt(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--tolerance", type=float, default=1.0)
    ap.add_argument("--drilldown", action="store_true",
                    help="refine close-rule exits with 1m drill-down (5m primary timeline)")
    args = ap.parse_args()

    start, end = _dt(args.start), _dt(args.end)
    db = AsyncAnalysisDB(os.environ["DATABASE_URL"])
    await db.connect()
    try:
        da = ParityDataAccess(db)
        kline_cache = KlineCacheService(db)

        trade_rows = await da.fetch_live_trades(args.account, start, end)
        cycles = build_cycles(trade_rows)
        if not cycles:
            print("No closed cycles found — check hydration (Task 0).")
            return
        scan_ids = [c.scan_id for c in cycles]
        signals = await da.fetch_signals(scan_ids)

        pinned, missing = pin_signals(signals, cycles, return_missing=True)
        if missing:
            print(f"WARNING: {len(missing)} pinned (scan,symbol,side) had no signal row: "
                  f"{sorted(missing)[:8]}...")

        symbols = sorted({s["ticker"] for s in pinned})
        klines = await da.fetch_klines(kline_cache, symbols, start, end, "5m")

        starting_capital = cycles[0].base_capital
        base_config = dict(CONFIG)
        base_config.update({"date_range_start": start, "date_range_end": end})

        # Per-cycle isolation: each cycle runs alone with its own live base_capital
        # and a fresh book (mirrors how live ran independent scheduled-scan cycles).
        signals_by_scan: dict[str, list] = {}
        for s in pinned:
            signals_by_scan.setdefault(s["scan_id"], []).append(s)

        # Optional 1m drill-down (CONTIGUOUS per-cycle window for correctness +
        # performance): refine close-rule exit prices to 1m within each 5m bar while
        # the 5m primary timeline keeps entry selection/fills stable. The window is
        # the cycle's ACTIVE span [first entry .. synchronized close] with small
        # padding — NOT the whole backtest range. Contiguous (not just entry/exit
        # bars) so the engine's book-wide equity walk (drawdown / target-goal) has 1m
        # coverage for EVERY position at the firing bar; isolated entry/exit bars
        # break that synchronization and let positions exit independently. Cycles are
        # short (minutes–hours), so the 1m fetch stays bounded; the 24h max-duration
        # cycles are the only long ones.
        fine_by_scan: dict[str, Any] | None = None
        if args.drilldown:
            fine_by_scan = {}
            for c in cycles:
                csyms = sorted({s["ticker"] for s in signals_by_scan.get(c.scan_id, [])})
                closes = [t.closed_at for t in c.live_trades if t.closed_at is not None]
                if not csyms or not closes:
                    continue
                w_start = c.signal_time - timedelta(hours=1)
                w_end = max(closes) + timedelta(hours=1)
                fine_by_scan[c.scan_id] = await da.build_fine_klines(
                    kline_cache, csyms, w_start, w_end, sim_interval_seconds=300)

        engine_trades = run_cycles_isolated(
            BacktestEngine(), cycles, signals_by_scan, klines, base_config,
            fine_klines_by_scan=fine_by_scan)

        report = build_report(cycles, engine_trades, starting_capital, args.tolerance)
        print(format_report(report))
        mode = "5m+1m drill-down" if args.drilldown else "5m"
        print(f"\nMode: {mode} | Live cycles: {len(cycles)} | pinned signals: {len(pinned)} | "
              f"engine closed trades: {len(engine_trades)}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
