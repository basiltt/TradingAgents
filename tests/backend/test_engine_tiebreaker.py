from datetime import datetime, timezone
from backend.services.backtest_engine import BacktestEngine

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _sig(ticker, score, completed_at, _id):
    return {"ticker": ticker, "score": score, "completed_at": completed_at,
            "id": _id, "direction": "sell"}

def test_rank_key_orders_by_score_then_completed_at_desc():
    # Four signals tied at |score|=7; live picks the LATEST completed_at first.
    sigs = [
        _sig("A", -7, _dt("2026-06-05T01:00:00"), 10),
        _sig("B", -7, _dt("2026-06-05T03:00:00"), 11),   # latest -> ranks first
        _sig("C", -7, _dt("2026-06-05T02:00:00"), 12),
        _sig("D", -8, _dt("2026-06-05T00:30:00"), 13),   # higher |score| -> absolute first
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["D", "B", "C", "A"]

def test_rank_key_exact_ties_preserve_input_order():
    sigs = [
        _sig("A", -7, _dt("2026-06-05T01:00:00"), 20),
        _sig("B", -7, _dt("2026-06-05T01:00:00"), 10),
        _sig("C", -7, _dt("2026-06-05T01:00:00"), 30),
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["A", "B", "C"]

def test_rank_key_nulls_sort_last_within_a_score_tie():
    sigs = [
        _sig("A", -7, None, 10),                          # NULL completed_at -> last
        _sig("B", -7, _dt("2026-06-05T01:00:00"), 11),
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["B", "A"]

def test_rank_key_uses_analysis_completed_at_when_completed_at_is_null():
    # Copied schedule rows can have scan_results.completed_at NULL even though
    # the live in-memory result had the analysis completion timestamp.
    sigs = [
        {"ticker": "OLDER", "score": -8, "completed_at": None,
         "analysis_completed_at": _dt("2026-06-05T01:00:00"), "direction": "sell"},
        {"ticker": "NEWER", "score": -8, "completed_at": None,
         "analysis_completed_at": _dt("2026-06-05T03:00:00"), "direction": "sell"},
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["NEWER", "OLDER"]

def test_fill_rank_key_ignores_analysis_completed_at_for_post_scan_recheck_order():
    sigs = [
        {"ticker": "OLDER", "score": -8, "completed_at": None,
         "analysis_completed_at": _dt("2026-06-05T01:00:00"), "direction": "sell"},
        {"ticker": "NEWER", "score": -8, "completed_at": None,
         "analysis_completed_at": _dt("2026-06-05T03:00:00"), "direction": "sell"},
    ]
    ordered = sorted(sigs, key=BacktestEngine._fill_rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["OLDER", "NEWER"]
