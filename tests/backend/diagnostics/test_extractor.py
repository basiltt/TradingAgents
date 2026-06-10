from datetime import datetime, timezone
from backend.diagnostics.parity.extractor import build_cycles, live_final_equity

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

TRADE_ROWS = [
    dict(symbol="ARKMUSDT", side="Sell", net_pnl=11.93, close_reason="rule_triggered",
         entry_price=0.13392, exit_price=0.12986, scan_result_id=1, status="closed",
         base_capital=200.43, scan_id="s1", signal_time=_dt("2026-06-05T01:28:00"),
         opened_at=_dt("2026-06-05T01:28:15"), closed_at=_dt("2026-06-05T04:43:25")),
    dict(symbol="MIRAUSDT", side="Sell", net_pnl=10.44, close_reason="rule_triggered",
         entry_price=0.0636, exit_price=0.06191, scan_result_id=2, status="closed",
         base_capital=200.43, scan_id="s1", signal_time=_dt("2026-06-05T01:28:00"),
         opened_at=_dt("2026-06-05T01:28:25"), closed_at=_dt("2026-06-05T04:43:25")),
    dict(symbol="EIGENUSDT", side="Sell", net_pnl=26.94, close_reason="rule_triggered",
         entry_price=0.17711, exit_price=0.16681, scan_result_id=3, status="closed",
         base_capital=234.02, scan_id="s2", signal_time=_dt("2026-06-05T06:40:00"),
         opened_at=_dt("2026-06-05T06:40:54"), closed_at=_dt("2026-06-05T08:19:56")),
    dict(symbol="MEGAUSDT", side="Sell", net_pnl=None, close_reason=None,
         entry_price=0.04727, exit_price=None, scan_result_id=9, status="open",
         base_capital=574.21, scan_id="s9", signal_time=_dt("2026-06-09T16:20:00"),
         opened_at=_dt("2026-06-09T16:20:26"), closed_at=None),
]

def test_build_cycles_groups_by_scan_excludes_open_and_orders():
    cycles = build_cycles(TRADE_ROWS)
    assert [c.scan_id for c in cycles] == ["s1", "s2"]
    assert cycles[0].pinned_set == {("ARKMUSDT", "sell"), ("MIRAUSDT", "sell")}
    assert cycles[0].base_capital == 200.43
    assert round(cycles[0].live_net_pnl, 2) == 22.37
    assert all(t.closed_at is not None for c in cycles for t in c.live_trades)

def test_live_final_equity_compounds():
    cycles = build_cycles(TRADE_ROWS)
    assert round(live_final_equity(cycles), 2) == round(200.43 + 22.37 + 26.94, 2)
