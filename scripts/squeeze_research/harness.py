"""Offline backtest research harness — drives the REAL BacktestEngine.

Goal: prove (or disprove) candidate squeeze-prevention filters OFFLINE, with
zero changes to the production repo. We do this by:

  1. Constructing the SAME AsyncAnalysisDB + KlineCacheService + BacktestService
     that backend/main.py wires at startup.
  2. Letting the REAL BacktestService._execute_backtest do ALL data loading
     (signals, klines, sector map, live-selection context, schedule times) so the
     engine inputs are byte-identical to a production backtest.
  3. Monkeypatching BacktestEngine.run at the CLASS level with a thin wrapper that
     (optionally) transforms the signals/config to apply a candidate filter, then
     delegates to the ORIGINAL run. The transform is supplied per-experiment.

Nothing here is imported by the app; it's a standalone research tool.

Run:  python -m scripts.squeeze_research.harness <experiment>
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# --- make repo importable + load env exactly like main.py ---
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT / ".env.enterprise", override=False)

from backend.async_persistence import AsyncAnalysisDB  # noqa: E402
from backend.services.backtest_service import BacktestService  # noqa: E402
from backend.services.kline_cache_service import KlineCacheService  # noqa: E402
from backend.services import backtest_engine as _engine_mod  # noqa: E402

BacktestEngine = _engine_mod.BacktestEngine
_ORIG_RUN = BacktestEngine.run  # the pristine engine entrypoint we always delegate to


# ---------------------------------------------------------------------------
# The exact config from the user's drawdown backtest (run 5460914a…), as a dict
# the service accepts. date fields are tz-aware datetimes (the service contract).
# ---------------------------------------------------------------------------
def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


BASE_CONFIG: dict[str, Any] = {
    "starting_capital": 234.0,
    "date_range_start": _dt("2026-06-04T18:30:00Z"),
    "date_range_end": _dt("2026-06-11T06:07:00Z"),
    "scan_source": {"mode": "schedule", "schedule_id": "d9c5f14f-a71f-4907-9449-dab3b75a52cb"},
    "simulation_interval": "5m",
    "fee_rate_pct": 0.055,
    "slippage_bps": 2,
    "funding_rate_model": "fixed_8h",
    "funding_rate_fixed_pct": 0.01,
    "direction": "straight",
    "leverage": 8,
    "capital_pct": 22.0,
    "take_profit_pct": 150.0,
    "stop_loss_pct": 100.0,
    "min_score": 7.0,
    "confidence_filter": "moderate",
    "signal_sides": "both",
    "max_trades": 3,
    "execution_mode": "batch",
    "fill_to_max_trades": True,
    "skip_if_positions_open": True,
    "max_same_direction": 3,
    "max_same_sector": 4,
    "symbol_blacklist": None,
    "symbol_whitelist": None,
    "max_signal_age_minutes": 150,
    "max_price_drift_pct": 6.0,
    "max_drawdown_pct": 12.0,
    "smart_drawdown_close": True,
    "breakeven_timeout_hours": None,
    "max_trade_duration_hours": 24.0,
    "trailing_profit_pct": 2.0,
    "close_on_profit_pct": None,
    "target_goal_type": "profit_pct",
    "target_goal_value": 15.0,
    "adaptive_blacklist_enabled": False,
    "adaptive_blacklist_min_trades": 5,
    "adaptive_blacklist_max_win_rate": 30.0,
    "adaptive_blacklist_lookback_hours": 48,
    "cooloff_on_success_enabled": False,
    "cooloff_on_success_minutes": None,
    "cooloff_on_failure_enabled": False,
    "cooloff_on_failure_minutes": None,
    "cooloff_on_double_success_enabled": False,
    "cooloff_on_double_success_minutes": None,
    "cooloff_on_double_failure_enabled": True,
    "cooloff_on_double_failure_minutes": 600,
    "regime_filter_enabled": False,
    "session_filter_enabled": False,
    "session_blocked_hours_utc": None,
    "session_allowed_hours_utc": None,
    "btc_vol_filter_enabled": False,
    "btc_vol_min_threshold": None,
    "btc_vol_max_threshold": None,
    "btc_vol_interval": "1h",
    "btc_vol_lookback_candles": 14,
    "mean_reversion_enabled": False,
    "mr_short_enabled": False,
    "mr_long_enabled": False,
    "mr_regime": "ranging",
    "mr_mean_period": 20,
    "mr_mean_interval": "1h",
    "mr_target_capture_pct": 60.0,
    "mr_tight_stop_pct": None,
    "mr_time_stop_minutes": 120,
    "mr_min_edge_pct": 1.0,
    "mr_extreme_min_abs_score": 5.0,
    "mr_capital_pct": 2.0,
    "mr_leverage": 10,
    "mr_max_trades": 2,
    "strategy_cohort": None,
    "regime_staleness_minutes": 30,
    "regime_volatile_atr": 2.0,
    "regime_trend_ema_dist_pct": 1.0,
}


# A "RunHook" gets called inside the patched engine.run with the live
# (config, signals, klines) and may return a (config, signals) pair to use
# instead. Returning None = no change (pristine baseline).
RunHook = Callable[[dict, list, dict], Optional[tuple[dict, list]]]


# Captures the LAST SimulationResult returned by the engine (the phase-B / full
# run is the last call), so experiments can diff actual trades without relying on
# the service's persisted output (which omits the trades array).
LAST_RESULT: dict[str, Any] = {"result": None}


def install_engine_hook(hook: Optional[RunHook]) -> None:
    """Class-level monkeypatch: wrap BacktestEngine.run with `hook`."""
    def patched_run(self, config, signals, klines, *args, **kwargs):
        if hook is not None:
            transformed = hook(config, signals, klines)
            if transformed is not None:
                config, signals = transformed
        res = _ORIG_RUN(self, config, signals, klines, *args, **kwargs)
        LAST_RESULT["result"] = res
        return res

    BacktestEngine.run = patched_run


def remove_engine_hook() -> None:
    BacktestEngine.run = _ORIG_RUN


async def build_service() -> tuple[BacktestService, AsyncAnalysisDB]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set (check .env)")
    db = AsyncAnalysisDB(dsn=dsn)
    await db.connect()
    kline_cache = KlineCacheService(db=db)
    svc = BacktestService(db=db, kline_cache=kline_cache)
    return svc, db


async def run_one(svc: BacktestService, config: dict, hook: Optional[RunHook] = None) -> dict:
    """Execute one backtest end-to-end via the REAL service, with an optional hook.

    Returns the persisted results dict (metrics + equity_curve + filter_stats).
    """
    run_id = f"research-{uuid.uuid4().hex[:12]}"
    # create_backtest validates + registers; but to keep full control we call the
    # internal execute path directly with a config the service accepts. We still
    # go through the public create to reserve a slot + persist a row.
    cfg = dict(config)
    install_engine_hook(hook)
    try:
        rid = await svc.create_backtest(cfg, client_id="research")
        # poll to completion
        for _ in range(600):
            await asyncio.sleep(0.25)
            row = await svc.get_backtest(rid)
            if row and row.get("status") in ("completed", "failed", "cancelled"):
                return row
        raise TimeoutError("backtest did not finish in time")
    finally:
        remove_engine_hook()


def summarize(row: dict, label: str) -> dict:
    r = (row or {}).get("results") or {}
    m = r.get("metrics") or {}
    out = {
        "label": label,
        "status": row.get("status"),
        "net_profit": m.get("net_profit"),
        "net_profit_pct": m.get("net_profit_pct"),
        "max_dd_pct": m.get("max_dd_pct"),
        "win_rate": m.get("win_rate"),
        "sharpe": m.get("sharpe"),
        "profit_factor": m.get("profit_factor"),
        "total_trades": m.get("total_trades"),
        "largest_loss": m.get("largest_loss"),
        "final_equity": m.get("final_equity"),
    }
    return out


def print_row(s: dict) -> None:
    def f(x, w=10, p=2):
        if x is None:
            return " " * (w - 2) + "--"
        return f"{x:>{w}.{p}f}"
    print(
        f"  {s['label']:<26}"
        f"{f(s['net_profit'])}"
        f"{f(s['net_profit_pct'])}"
        f"{f(s['max_dd_pct'])}"
        f"{f(s['win_rate'])}"
        f"{f(s['sharpe'])}"
        f"{f(s['profit_factor'])}"
        f"{(str(s['total_trades']) if s['total_trades'] is not None else '--'):>6}"
        f"{f(s['largest_loss'])}"
    )


def print_header() -> None:
    print(
        f"  {'experiment':<26}"
        f"{'net$':>10}{'net%':>10}{'maxDD%':>10}{'win%':>10}"
        f"{'sharpe':>10}{'PF':>10}{'trades':>6}{'maxLoss$':>10}"
    )
    print("  " + "-" * 102)


# ---------------------------------------------------------------------------
# Experiment registry — each returns a RunHook (or None for baseline).
# ---------------------------------------------------------------------------
def exp_baseline() -> Optional[RunHook]:
    return None


EXPERIMENTS: dict[str, Callable[[], Optional[RunHook]]] = {
    "baseline": exp_baseline,
}


async def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    svc, db = await build_service()
    try:
        print_header()
        if which == "baseline":
            row = await run_one(svc, BASE_CONFIG, None)
            s = summarize(row, "baseline (pristine)")
            print_row(s)
            # sanity vs the known MCP result
            m = (row.get("results") or {}).get("metrics") or {}
            exp_net, exp_dd = 999.9207011072158, 17.910244812110403
            got_net, got_dd = m.get("net_profit"), m.get("max_dd_pct")
            ok = (got_net is not None and abs(got_net - exp_net) < 1e-6
                  and abs(got_dd - exp_dd) < 1e-9)
            print(f"\n  fidelity check vs MCP run 5460914a: "
                  f"net {got_net} (exp {exp_net}), dd {got_dd} (exp {exp_dd}) "
                  f"=> {'BIT-EXACT ✓' if ok else 'MISMATCH ✗'}")
        else:
            print(f"unknown experiment: {which}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
