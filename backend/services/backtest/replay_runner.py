"""Replay-mode runner: validate the engine against an account's ACTUAL live trades.

Pins the account's real traded symbols (selection from ground truth) and replays them
through BacktestEngine per cycle, then builds a live-vs-backtest comparison. Reuses the
parity harness units — does NOT re-implement the engine.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import run_cycles_isolated, build_report


def _correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx ** 0.5 * vy ** 0.5)


async def run_replay(
    data_access: Any, kline_cache: Any, account_id: str,
    start: datetime, end: datetime, base_config: dict[str, Any],
    drilldown: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (result_dict, replay_comparison).

    result_dict mimics SimulationResult enough for persistence: {trades, equity_curve}.
    replay_comparison: per-cycle live-vs-backtest + headline fidelity stats.
    """
    trade_rows = await data_access.fetch_live_trades(account_id, start, end)
    cycles = build_cycles(trade_rows)
    if not cycles:
        return ({"trades": [], "equity_curve": [], "starting_capital": 0.0},
                {"n_cycles": 0, "pinned_trades": 0, "cycles": [],
                 "final_equity_delta_pct": 0.0, "pnl_correlation": 0.0,
                 "directional_agreement": 0, "note": "no closed cycles in range"})

    signals = await data_access.fetch_signals([c.scan_id for c in cycles])
    pinned, _missing = pin_signals(signals, cycles, return_missing=True)

    signals_by_scan: dict[str, list] = {}
    for s in pinned:
        signals_by_scan.setdefault(s["scan_id"], []).append(s)

    klines = await data_access.fetch_klines(
        kline_cache, sorted({s["ticker"] for s in pinned}), start, end, "5m")

    cfg = dict(base_config)
    cfg.update({"date_range_start": start, "date_range_end": end})

    fine_by_scan: dict[str, Any] | None = None
    if drilldown and kline_cache is not None:
        fine_by_scan = {}
        for c in cycles:
            csyms = sorted({s["ticker"] for s in signals_by_scan.get(c.scan_id, [])})
            closes = [t.closed_at for t in c.live_trades if t.closed_at]
            if not csyms or not closes:
                continue
            fine_by_scan[c.scan_id] = await data_access.build_fine_klines(
                kline_cache, csyms, c.signal_time - timedelta(hours=1),
                max(closes) + timedelta(hours=1), sim_interval_seconds=300)

    engine_trades = run_cycles_isolated(
        BacktestEngine(), cycles, signals_by_scan, klines, cfg,
        fine_klines_by_scan=fine_by_scan)

    starting_capital = cycles[0].base_capital
    report = build_report(cycles, engine_trades, starting_capital, tolerance_pct=1.0)

    live_pnls = [cc.live_net_pnl for cc in report.cycles]
    bt_pnls = [cc.backtest_net_pnl for cc in report.cycles]
    comparison = {
        "n_cycles": len(report.cycles),
        "pinned_trades": len(pinned),
        "live_final_equity": report.live_final_equity,
        "backtest_final_equity": report.backtest_final_equity,
        "final_equity_delta_pct": report.final_equity_delta_pct,
        "pnl_correlation": _correlation(live_pnls, bt_pnls),
        "directional_agreement": sum(
            1 for a, b in zip(live_pnls, bt_pnls) if (a >= 0) == (b >= 0)),
        "cycles": [
            {"scan_id": cc.scan_id, "signal_time": cc.signal_time,
             "live_net_pnl": cc.live_net_pnl, "backtest_net_pnl": cc.backtest_net_pnl,
             "live_equity_after": cc.live_equity_after,
             "backtest_equity_after": cc.backtest_equity_after,
             "delta_pct": cc.delta_pct}
            for cc in report.cycles
        ],
    }
    # equity_curve for the normal dashboard: compounded backtest equity per cycle.
    # Emit drawdown_pct so the shape matches the engine's points (the service's
    # _downsample_equity reads .get("drawdown_pct") — present here for clarity/parity).
    _peak = float("-inf")
    equity_curve = []
    for cc in report.cycles:
        eq = cc.backtest_equity_after
        _peak = max(_peak, eq)
        dd = round(((eq - _peak) / _peak) * 100.0, 4) if _peak > 0 else 0.0
        equity_curve.append({"ts": cc.signal_time, "equity": eq, "drawdown_pct": dd})
    result = {"trades": engine_trades, "equity_curve": equity_curve,
              "starting_capital": starting_capital}
    return result, comparison
