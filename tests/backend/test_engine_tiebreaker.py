from datetime import datetime, timezone
from backend.services.backtest_engine import BacktestEngine

def _dt(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def _sig(ticker, score, completed_at, _id):
    return {"ticker": ticker, "score": score, "analysis_completed_at": completed_at,
            "id": _id, "direction": "sell"}

def test_rank_key_orders_by_score_then_completed_at_desc_then_id():
    # Four signals tied at |score|=7; live picks the LATEST completed_at first.
    sigs = [
        _sig("A", -7, _dt("2026-06-05T01:00:00"), 10),
        _sig("B", -7, _dt("2026-06-05T03:00:00"), 11),   # latest -> ranks first
        _sig("C", -7, _dt("2026-06-05T02:00:00"), 12),
        _sig("D", -8, _dt("2026-06-05T00:30:00"), 13),   # higher |score| -> absolute first
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["D", "B", "C", "A"]

def test_rank_key_nulls_sort_last_within_a_score_tie():
    sigs = [
        _sig("A", -7, None, 10),                          # NULL completed_at -> last
        _sig("B", -7, _dt("2026-06-05T01:00:00"), 11),
    ]
    ordered = sorted(sigs, key=BacktestEngine._rank_key, reverse=True)
    assert [s["ticker"] for s in ordered] == ["B", "A"]
