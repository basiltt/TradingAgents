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


def test_run_cycles_isolated_uses_own_base_capital_and_fresh_book():
    """Per-cycle isolation: each cycle runs alone with its own base_capital and a
    fresh book, then results are stamped with the cycle's scan_id so build_report
    can compound them. Uses a fake engine to stay pure (no DB/klines)."""
    from backend.diagnostics.parity.reporter import run_cycles_isolated

    c1 = _cycle("s1", 200.0, [10.0, 12.0], _dt("2026-06-05T01:28:00"))
    c2 = _cycle("s2", 222.0, [26.0], _dt("2026-06-05T06:40:00"))
    signals_by_scan = {
        "s1": [{"scan_id": "s1", "ticker": "S0"}, {"scan_id": "s1", "ticker": "S1"}],
        "s2": [{"scan_id": "s2", "ticker": "S0"}],
    }

    class FakeResult:
        def __init__(self, trades): self.trades = trades

    class FakeEngine:
        def __init__(self): self.seen_capital = []
        def run(self, config, signals, klines, **kw):
            self.seen_capital.append(config["starting_capital"])
            # echo one trade per input signal with pnl=1.0
            return FakeResult([{"pnl": 1.0} for _ in signals])

    eng = FakeEngine()
    base_cfg = {"leverage": 10}
    engine_trades = run_cycles_isolated(eng, [c1, c2], signals_by_scan, klines={},
                                        base_config=base_cfg)
    # each cycle ran with its OWN base_capital
    assert eng.seen_capital == [200.0, 222.0]
    # trades are stamped with their cycle scan_id for build_report compounding
    by_scan = {}
    for t in engine_trades:
        by_scan[t["scan_id"]] = by_scan.get(t["scan_id"], 0) + 1
    assert by_scan == {"s1": 2, "s2": 1}


def test_run_cycles_isolated_passes_per_cycle_fine_klines():
    """When fine_klines_by_scan is supplied, each cycle's 1m drill-down windows are
    passed to the engine via the fine_klines kwarg (5m primary + 1m exit refinement)."""
    from backend.diagnostics.parity.reporter import run_cycles_isolated

    c1 = _cycle("s1", 200.0, [10.0], _dt("2026-06-05T01:28:00"))
    signals_by_scan = {"s1": [{"scan_id": "s1", "ticker": "S0"}]}
    fine_by_scan = {"s1": {"S0": {123: [{"open_time": _dt("2026-06-05T01:28:00")}]}}}

    class FakeResult:
        def __init__(self, trades): self.trades = trades

    class FakeEngine:
        def __init__(self): self.seen_fine = []
        def run(self, config, signals, klines, **kw):
            self.seen_fine.append(kw.get("fine_klines"))
            return FakeResult([{"pnl": 1.0}])

    eng = FakeEngine()
    run_cycles_isolated(eng, [c1], signals_by_scan, klines={}, base_config={},
                        fine_klines_by_scan=fine_by_scan)
    assert eng.seen_fine == [fine_by_scan["s1"]]
