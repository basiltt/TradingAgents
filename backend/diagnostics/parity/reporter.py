"""Build the parity report: live cycles vs engine SimulationResult.trades."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import Cycle, CycleComparison, ParityReport
from backend.diagnostics.parity.extractor import live_final_equity


def run_cycles_isolated(
    engine: Any,
    cycles: list[Cycle],
    signals_by_scan: Mapping[str, list[Mapping[str, Any]]],
    klines: Mapping[str, list[dict]],
    base_config: Mapping[str, Any],
    fine_klines_by_scan: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run each pinned cycle in ISOLATION and return scan-stamped engine trades.

    Live operated each scheduled-scan cycle independently: a cycle opens, closes by
    its own rules, and the next scan trades against a fresh book with a freshly
    compounded base_capital. The production engine instead replays all scans on one
    carried timeline, so a mistimed close + skip_if_positions_open cascades into
    wholly-skipped cycles. For a SELECTIVE replay (membership already pinned from
    ground truth) the faithful model is per-cycle isolation.

    Each cycle runs with its OWN live base_capital as starting_capital and a fresh
    engine state. Returned engine-trade dicts are stamped with their cycle's scan_id
    so build_report() can compound per-cycle PnL against the live oracle.

    When fine_klines_by_scan is supplied, each cycle's 1m drill-down windows
    ({symbol: {bar_open_epoch: [1m candles]}}) are passed to the engine so its
    close-rule EXIT prices refine to 1m granularity while the 5m primary timeline
    keeps entry selection/fills stable (matches how live fired its ~60s-poll closes
    without shifting which bar a trade entered on).
    """
    out: list[dict[str, Any]] = []
    for c in cycles:
        sigs = list(signals_by_scan.get(c.scan_id, []))
        if not sigs:
            continue
        cfg = dict(base_config)
        cfg["starting_capital"] = c.base_capital
        kwargs: dict[str, Any] = {}
        if fine_klines_by_scan is not None:
            fine = fine_klines_by_scan.get(c.scan_id)
            if fine:
                kwargs["fine_klines"] = fine
        result = engine.run(cfg, sigs, klines, **kwargs)
        for t in result.trades:
            rec = dict(t)
            rec["scan_id"] = c.scan_id          # stamp for build_report compounding
            out.append(rec)
    return out


def build_report(
    cycles: list[Cycle],
    engine_trades: list[Mapping[str, Any]],
    starting_capital: float,
    tolerance_pct: float = 1.0,
) -> ParityReport:
    """Compare per-cycle live vs engine PnL and compound both equity curves."""
    bt_by_scan: dict[str, float] = {}
    for t in engine_trades:
        sid = t.get("scan_id", "")
        bt_by_scan[sid] = bt_by_scan.get(sid, 0.0) + float(t.get("pnl", 0.0))

    comparisons: list[CycleComparison] = []
    live_eq = starting_capital
    bt_eq = starting_capital
    for c in cycles:
        live_pnl = c.live_net_pnl
        bt_pnl = bt_by_scan.get(c.scan_id, 0.0)
        live_eq += live_pnl
        bt_eq += bt_pnl
        comparisons.append(CycleComparison(
            scan_id=c.scan_id, signal_time=c.signal_time,
            live_net_pnl=live_pnl, backtest_net_pnl=bt_pnl,
            live_equity_after=live_eq, backtest_equity_after=bt_eq,
        ))

    return ParityReport(
        live_final_equity=live_final_equity(cycles),
        backtest_final_equity=bt_eq,
        cycles=comparisons,
        tolerance_pct=tolerance_pct,
    )


def format_report(report: ParityReport) -> str:
    """Human-readable per-cycle table + headline. Used by the CLI."""
    lines = [
        f"{'cycle (scan)':<14} {'live_pnl':>10} {'bt_pnl':>10} {'live_eq':>10} {'bt_eq':>10} {'delta%':>8}",
        "-" * 66,
    ]
    for c in report.cycles:
        lines.append(f"{c.scan_id[:12]:<14} {c.live_net_pnl:>10.2f} {c.backtest_net_pnl:>10.2f} "
                     f"{c.live_equity_after:>10.2f} {c.backtest_equity_after:>10.2f} {c.delta_pct:>8.2f}")
    lines.append("-" * 66)
    lines.append(f"LIVE final equity:     {report.live_final_equity:.2f}")
    lines.append(f"BACKTEST final equity: {report.backtest_final_equity:.2f}")
    lines.append(f"FINAL DELTA: {report.final_equity_delta_pct:+.2f}%  "
                 f"=> {'PASS' if report.passed else 'FAIL'} (tol {report.tolerance_pct}%)")
    return "\n".join(lines)
