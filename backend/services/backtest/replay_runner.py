"""Replay-mode runner: validate the engine against an account's ACTUAL live trades.

Pins the account's real traded symbols (selection from ground truth) and replays them
through BacktestEngine per cycle, then builds a live-vs-backtest comparison. Reuses the
parity harness units — does NOT re-implement the engine.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

from backend.services.backtest_engine import BacktestEngine
from backend.diagnostics.parity.extractor import build_cycles
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.reporter import run_cycles_isolated, build_report

# Bounds so a replay over a large/live account can't OOM (klines) or flood the
# exchange (per-trade 1m drill fetches) or write an unbounded comparison blob.
_MAX_CYCLES = 200
_MAX_SYMBOLS = 300


class ReplayError(Exception):
    """Replay cannot produce a meaningful comparison (no cycles, or over a bound).

    Mapped by the service to a failed run with this message, so the user sees WHY
    rather than a silent empty/garbage result.
    """


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
    drilldown: bool = True, run_sync: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (result_dict, replay_comparison).

    result_dict mimics SimulationResult enough for persistence: {trades, equity_curve}.
    replay_comparison: per-cycle live-vs-backtest + headline fidelity stats.

    `run_sync`, when provided, is an awaitable wrapper (e.g. loop.run_in_executor) that
    runs the CPU-bound, synchronous cycle-replay OFF the event loop. Called as
    `await run_sync(fn)` where fn is a zero-arg callable returning the engine trades.
    When None, the simulation runs inline (fine for tests / small replays).

    Raises ReplayError when there are no pinnable cycles, or the work exceeds the
    cycle/symbol bounds — so the service can fail the run with a clear reason rather
    than persist an empty/garbage comparison.
    """
    trade_rows = await data_access.fetch_live_trades(account_id, start, end)
    cycles = build_cycles(trade_rows)
    excluded = {}
    if hasattr(data_access, "fetch_excluded_counts"):
        excluded = await data_access.fetch_excluded_counts(account_id, start, end)

    if not cycles:
        raise ReplayError(
            "No scanner trades to replay in this window for this account. "
            "(Replay excludes AI-Manager-closed and non-scanner trades.) "
            f"Excluded in window: {excluded or 'n/a'}.")
    if len(cycles) > _MAX_CYCLES:
        raise ReplayError(
            f"Replay window has {len(cycles)} cycles (max {_MAX_CYCLES}). "
            "Narrow the date range.")

    signals = await data_access.fetch_signals([c.scan_id for c in cycles])
    pinned, missing = pin_signals(signals, cycles, return_missing=True)

    symbols = sorted({s["ticker"] for s in pinned})
    if len(symbols) > _MAX_SYMBOLS:
        raise ReplayError(
            f"Replay touches {len(symbols)} symbols (max {_MAX_SYMBOLS}). "
            "Narrow the date range.")

    signals_by_scan: dict[str, list] = {}
    for s in pinned:
        signals_by_scan.setdefault(s["scan_id"], []).append(s)

    klines = await data_access.fetch_klines(kline_cache, symbols, start, end, "5m")
    # Coverage guard: a pinned symbol with NO cached candles can't be simulated, so the
    # engine skips it and the comparison silently under-trades. Count them for disclosure.
    symbols_no_kline = sum(1 for s in symbols if not klines.get(s))

    cfg = dict(base_config)
    cfg.update({"date_range_start": start, "date_range_end": end})

    # SCOPED 1m drill-down: per cycle, fetch 1m ONLY around each trade's entry+exit
    # bars (build_fine_klines_scoped) — NOT the whole multi-hour cycle window — so a
    # many-cycle replay doesn't issue an unbounded number of full-window exchange
    # fetches. Skipped when no cache (engine falls back to 5m exits).
    fine_by_scan: dict[str, Any] | None = None
    if drilldown and kline_cache is not None and hasattr(data_access, "build_fine_klines_scoped"):
        fine_by_scan = {}
        for c in cycles:
            windows = [
                (t.symbol, t.opened_at, t.closed_at)
                for t in c.live_trades if t.closed_at is not None
            ]
            if not windows:
                continue
            fine_by_scan[c.scan_id] = await data_access.build_fine_klines_scoped(
                kline_cache, windows, sim_interval_seconds=300, neighbour_bars=1)

    # Run the synchronous per-cycle engine replay OFF the event loop when a run_sync
    # wrapper is supplied (the service passes loop.run_in_executor). The engine is
    # CPU-bound; running it inline would block all other async request handling.
    def _do_cycles() -> list[dict[str, Any]]:
        return run_cycles_isolated(
            BacktestEngine(), cycles, signals_by_scan, klines, cfg,
            fine_klines_by_scan=fine_by_scan)

    if run_sync is not None:
        engine_trades = await run_sync(_do_cycles)
    else:
        engine_trades = _do_cycles()

    starting_capital = cycles[0].base_capital
    report = build_report(cycles, engine_trades, starting_capital, tolerance_pct=1.0)

    live_pnls = [cc.live_net_pnl for cc in report.cycles]
    bt_pnls = [cc.backtest_net_pnl for cc in report.cycles]
    comparison = {
        "n_cycles": len(report.cycles),
        "pinned_trades": len(pinned),
        # Data-integrity disclosure — fidelity is computed over the pinned set only.
        "missing_pins": len(missing),
        "excluded_trades": excluded,
        "symbols_no_kline": symbols_no_kline,
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
