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
from datetime import datetime, timezone

from backend.async_persistence import AsyncAnalysisDB
from backend.services.kline_cache_service import KlineCacheService
from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.data_access import ParityDataAccess
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import build_report, format_report, run_cycles_isolated

# Dad - Demo config under test (see plan Reference Facts).
CONFIG = {
    "leverage": 10, "capital_pct": 20, "max_trades": 3, "take_profit_pct": 150,
    "stop_loss_pct": 100, "max_drawdown_pct": 12, "smart_drawdown_close": True,
    "trailing_profit_pct": 2, "breakeven_timeout_hours": 12, "max_trade_duration_hours": 24,
    "min_score": 7, "confidence_filter": "moderate", "signal_sides": "both",
    "execution_mode": "batch", "fill_to_max_trades": True, "skip_if_positions_open": True,
    "adaptive_blacklist_enabled": True, "adaptive_blacklist_min_trades": 5,
    "adaptive_blacklist_max_win_rate": 30, "adaptive_blacklist_lookback_hours": 48,
    "target_goal_type": "profit_pct", "target_goal_value": 15, "max_price_drift_pct": 3,
    "max_same_sector": 2, "max_same_direction": 3, "direction": "straight",
    "fee_rate_pct": 0.055, "slippage_bps": 2, "simulation_interval": "5m",
}


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
        engine_trades = run_cycles_isolated(
            BacktestEngine(), cycles, signals_by_scan, klines, base_config)

        report = build_report(cycles, engine_trades, starting_capital, args.tolerance)
        print(format_report(report))
        print(f"\nLive cycles: {len(cycles)} | pinned signals: {len(pinned)} | "
              f"engine closed trades: {len(engine_trades)}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
