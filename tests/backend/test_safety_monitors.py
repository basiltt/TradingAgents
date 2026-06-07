"""Tests for FR-065: F2-long drawdown breaker + F1 suppression-rate alert (T-18).

Asserts the EXACT trip points pinned as SD22 constants:
  * breaker trips only on a full 20-trade window with summed PnL% <= -15%
  * suppression alert fires only when rate strictly exceeds 0.95
  * a breaker trip writes the f2_long kill switch
"""

from __future__ import annotations

import pytest

from backend.services import safety_monitors as sm


# --- breaker_should_trip: exact boundaries ---------------------------------------

def test_breaker_needs_full_window():
    # 19 trades summing to -100% still does NOT trip (insufficient evidence).
    assert sm.breaker_should_trip([-100.0 / 19] * 19) is False


def test_breaker_trips_exactly_at_threshold():
    # 20 trades summing to exactly -15% trips (<= threshold).
    pnls = [-15.0 / 20] * 20
    assert sm.breaker_should_trip(pnls) is True


def test_breaker_does_not_trip_just_above_threshold():
    # summed -14.99% must NOT trip.
    pnls = [-14.99 / 20] * 20
    assert sm.breaker_should_trip(pnls) is False


def test_breaker_uses_only_last_window():
    # 30 trades; the last 20 are mildly positive -> no trip despite old losses.
    old_losses = [-50.0] * 10
    recent_ok = [0.5] * 20
    assert sm.breaker_should_trip(old_losses + recent_ok) is False


def test_breaker_trips_on_recent_window_even_with_good_history():
    good_history = [10.0] * 10
    recent_bad = [-1.0] * 20  # sums to -20%
    assert sm.breaker_should_trip(good_history + recent_bad) is True


# --- suppression_should_alert: strict > 0.95 -------------------------------------

def test_suppression_alert_strictly_above_threshold():
    assert sm.suppression_should_alert(96, 100) is True   # 0.96 > 0.95
    assert sm.suppression_should_alert(95, 100) is False  # 0.95 not > 0.95


def test_suppression_alert_empty_never_fires():
    assert sm.suppression_should_alert(0, 0) is False


def test_f1_suppression_alert_aggregates_recent_scans():
    # 8 scans each 10/10 suppressed -> 100% -> alerts and returns the rate.
    scans = [(10, 10)] * 8
    assert sm.f1_suppression_alert(scans) == pytest.approx(1.0)


def test_f1_suppression_alert_below_threshold_returns_none():
    scans = [(9, 10)] * 8  # 90% < 95%
    assert sm.f1_suppression_alert(scans) is None


def test_f1_suppression_alert_only_counts_last_8_scans():
    # 4 early all-suppressed scans + 8 calm scans -> windowed to the calm 8 -> None.
    scans = [(10, 10)] * 4 + [(0, 10)] * 8
    assert sm.f1_suppression_alert(scans) is None


# --- check_f2_long_breaker: DB driver writes the kill ----------------------------

class _FakePool:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []
        self.fetch_sql = None

    async def fetch(self, sql, *args):
        self.fetch_sql = sql
        assert "strategy_kind = 'mean_reversion'" in sql
        assert "side = 'Buy'" in sql
        return self._rows

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "INSERT 0 1"


class _FakeDB:
    def __init__(self, rows):
        self.pool = _FakePool(rows)


@pytest.mark.asyncio
async def test_check_breaker_trips_and_writes_kill():
    rows = [{"realized_pnl_pct": -1.0}] * 20  # -20%
    db = _FakeDB(rows)
    tripped = await sm.check_f2_long_breaker(db, "acct1")
    assert tripped is True
    # the f2_long kill row was upserted to killed=True
    insert = [e for e in db.pool.executed if "feature_kill_switches" in e[0]]
    assert len(insert) == 1
    assert insert[0][1][0] == "f2_long" and insert[0][1][1] is True


@pytest.mark.asyncio
async def test_check_breaker_does_not_write_when_safe():
    rows = [{"realized_pnl_pct": 1.0}] * 20  # +20%
    db = _FakeDB(rows)
    tripped = await sm.check_f2_long_breaker(db, "acct1")
    assert tripped is False
    assert db.pool.executed == []


@pytest.mark.asyncio
async def test_check_breaker_failopen_on_query_error():
    class _BoomDB:
        class pool:
            @staticmethod
            async def fetch(*a, **k):
                raise RuntimeError("db down")
    assert await sm.check_f2_long_breaker(_BoomDB(), "acct1") is False


@pytest.mark.asyncio
async def test_check_breaker_excludes_partial_close_children():
    # Partial closes create child rows; the breaker window must count only parents
    # (parent_trade_id IS NULL) so one position cannot fill the 20-trade window.
    rows = [{"realized_pnl_pct": -1.0}] * 20
    db = _FakeDB(rows)
    await sm.check_f2_long_breaker(db, "acct1")
    assert "parent_trade_id IS NULL" in db.pool.fetch_sql
