from datetime import datetime, timezone
from backend.diagnostics.parity.shim import pin_signals
from backend.diagnostics.parity.models import LiveTrade, Cycle

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _sig(scan_id, ticker, direction, score):
    return {"scan_id": scan_id, "ticker": ticker, "direction": direction,
            "score": score, "signal_time": _dt("2026-06-05T01:28:00"),
            "confidence": "high", "analysis_price": 1.0}

SIGNALS = [
    _sig("s1", "ARKMUSDT", "sell", -8),
    _sig("s1", "MIRAUSDT", "sell", -8),
    _sig("s1", "PENDLEUSDT", "sell", -8),
    _sig("s1", "ZZZUSDT", "sell", -8),
    _sig("s1", "WWWUSDT", "sell", -7),
]

def _cycle(scan_id, pins):
    trades = [LiveTrade(sym, side.title(), 1.0, "rule_triggered", 1.0, 1.0, i,
                        _dt("2026-06-05T01:28:15"), _dt("2026-06-05T04:43:25"))
              for i, (sym, side) in enumerate(pins)]
    return Cycle(scan_id, _dt("2026-06-05T01:28:00"), 200.43, trades)

def test_pin_signals_keeps_only_pinned_symbols():
    cycles = [_cycle("s1", [("ARKMUSDT", "sell"), ("MIRAUSDT", "sell"), ("PENDLEUSDT", "sell")])]
    out = pin_signals(SIGNALS, cycles)
    kept = {(s["ticker"], s["direction"]) for s in out}
    assert kept == {("ARKMUSDT", "sell"), ("MIRAUSDT", "sell"), ("PENDLEUSDT", "sell")}
    assert ("ZZZUSDT", "sell") not in kept

def test_pin_signals_matches_side_case_insensitively():
    cycles = [_cycle("s1", [("ARKMUSDT", "Sell")])]
    out = pin_signals(SIGNALS, cycles)
    assert {(s["ticker"], s["direction"]) for s in out} == {("ARKMUSDT", "sell")}

def test_pin_signals_drops_scans_with_no_cycle():
    extra = SIGNALS + [_sig("s2", "FOOUSDT", "buy", 9)]
    cycles = [_cycle("s1", [("ARKMUSDT", "sell")])]
    out = pin_signals(extra, cycles)
    assert all(s["scan_id"] == "s1" for s in out)

def test_pin_signals_reports_missing_pins():
    cycles = [_cycle("s1", [("ARKMUSDT", "sell"), ("NOSIGNALUSDT", "sell")])]
    out, missing = pin_signals(SIGNALS, cycles, return_missing=True)
    assert ("s1", "NOSIGNALUSDT", "sell") in missing
