from datetime import datetime, timezone
from backend.diagnostics.parity.reporter import build_report
from backend.diagnostics.parity.models import LiveTrade, Cycle

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _cycle(scan_id, base, pnls, t0):
    trades = [LiveTrade(f"S{i}", "Sell", p, "rule_triggered", 1.0, 1.0, i, t0, t0)
              for i, p in enumerate(pnls)]
    return Cycle(scan_id, t0, base, trades)

def test_build_report_matches_when_engine_equals_live():
    cycles = [
        _cycle("s1", 200.0, [10.0, 12.0], _dt("2026-06-05T01:28:00")),
        _cycle("s2", 222.0, [26.0], _dt("2026-06-05T06:40:00")),
    ]
    engine_trades = [
        {"scan_id": "s1", "pnl": 10.0}, {"scan_id": "s1", "pnl": 12.0},
        {"scan_id": "s2", "pnl": 26.0},
    ]
    report = build_report(cycles, engine_trades, starting_capital=200.0, tolerance_pct=1.0)
    assert round(report.live_final_equity, 2) == 248.0
    assert round(report.backtest_final_equity, 2) == 248.0
    assert report.passed is True
    assert len(report.cycles) == 2
    assert round(report.cycles[0].backtest_net_pnl, 2) == 22.0

def test_build_report_fails_when_engine_diverges():
    cycles = [_cycle("s1", 200.0, [10.0, 12.0], _dt("2026-06-05T01:28:00"))]
    engine_trades = [{"scan_id": "s1", "pnl": -50.0}, {"scan_id": "s1", "pnl": 12.0}]
    report = build_report(cycles, engine_trades, starting_capital=200.0, tolerance_pct=1.0)
    assert report.passed is False
