"""Build the parity report: live cycles vs engine SimulationResult.trades."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import Cycle, CycleComparison, ParityReport
from backend.diagnostics.parity.extractor import live_final_equity


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
