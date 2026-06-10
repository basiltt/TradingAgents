from datetime import datetime, timezone
from backend.diagnostics.parity.models import LiveTrade, Cycle, CycleComparison, ParityReport


def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_live_trade_pin_key_normalizes_side():
    t = LiveTrade("ARKMUSDT", "Sell", 11.93, "rule_triggered", 0.13392, 0.12986, 59771,
                  _dt("2026-06-05T01:28:15"), _dt("2026-06-05T04:43:25"))
    assert t.pin_key == ("ARKMUSDT", "sell")
    assert t.is_external is False


def test_cycle_pinned_set_and_net_pnl():
    t1 = LiveTrade("ARKMUSDT", "Sell", 11.93, "rule_triggered", 0.1, 0.1, 1, _dt("2026-06-05T01:28:15"), _dt("2026-06-05T04:43:25"))
    t2 = LiveTrade("MIRAUSDT", "Sell", 10.44, "external", 0.1, 0.1, 2, _dt("2026-06-05T01:28:25"), _dt("2026-06-05T04:43:25"))
    c = Cycle("s1", _dt("2026-06-05T01:28:00"), 200.43, [t1, t2])
    assert c.pinned_set == {("ARKMUSDT", "sell"), ("MIRAUSDT", "sell")}
    assert round(c.live_net_pnl, 2) == 22.37
    assert t2.is_external is True


def test_report_pass_within_tolerance():
    r = ParityReport(602.61, 600.00, [], tolerance_pct=1.0)
    assert r.passed is True


def test_report_fail_outside_tolerance():
    r = ParityReport(602.61, 500.00, [], tolerance_pct=1.0)
    assert r.passed is False
