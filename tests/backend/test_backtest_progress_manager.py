"""Tests for BacktestProgressManager — the real-time stage event pub/sub."""

from __future__ import annotations

import asyncio

import pytest

from backend.services.backtest_progress_manager import BacktestProgressManager


def test_emit_records_history_with_monotonic_seq():
    m = BacktestProgressManager()
    m.emit("r1", "loading_signals", "Loading", detail="x", pct=0)
    m.emit("r1", "warming_cache", "Warming", pct=2)
    hist = m.history("r1")
    assert [e["stage"] for e in hist] == ["loading_signals", "warming_cache"]
    assert [e["seq"] for e in hist] == [1, 2]  # monotonic
    assert hist[0]["detail"] == "x"
    assert hist[0]["type"] == "backtest_progress"


def test_subscribe_replays_history_then_receives_live():
    m = BacktestProgressManager()
    m.emit("r1", "loading_signals", "Loading", pct=0)  # before subscribe
    q = m.subscribe("r1")
    # History replayed into the queue.
    assert q.get_nowait()["stage"] == "loading_signals"
    # Live event after subscribe.
    m.emit("r1", "simulating", "Simulating", pct=50)
    assert q.get_nowait()["stage"] == "simulating"


def test_subscribe_is_run_scoped():
    m = BacktestProgressManager()
    qa = m.subscribe("rA")
    m.emit("rB", "loading_signals", "Loading")  # different run
    assert qa.empty()  # rA subscriber sees nothing from rB
    m.emit("rA", "loading_signals", "Loading")
    assert qa.get_nowait()["run_id"] == "rA"


def test_unsubscribe_stops_delivery():
    m = BacktestProgressManager()
    q = m.subscribe("r1")
    m.unsubscribe("r1", q)
    m.emit("r1", "simulating", "Simulating")
    assert q.empty()


def test_done_status_marks_terminal_stage():
    m = BacktestProgressManager()
    ev = m.emit("r1", "complete", "Done", pct=100, status="done")
    assert ev["status"] == "done"
    assert ev["stage"] == "complete"
    # terminal_at recorded → run is eligible for GC after retention
    assert "r1" in m._terminal_at  # internal but the contract we rely on


def test_full_subscriber_queue_drops_oldest_not_raises():
    m = BacktestProgressManager()
    q = m.subscribe("r1")
    # Fill beyond the queue maxsize; emit must never raise even if a subscriber lags.
    for i in range(500):
        m.emit("r1", f"stage_{i}", "x", pct=i % 100)
    # Still functional — the queue holds a bounded number, newest retained.
    assert not q.empty()


class _StageRecorder:
    """A fake progress manager that just records emitted stages (for service test)."""

    def __init__(self):
        self.events = []

    def emit(self, run_id, stage, label, *, detail="", pct=None, status="active"):
        self.events.append({"run_id": run_id, "stage": stage, "status": status})
        return {}


@pytest.mark.asyncio
async def test_service_emits_stage_when_manager_present(monkeypatch):
    """BacktestService._emit_stage forwards to the manager and never raises."""
    from backend.services.backtest_service import BacktestService

    rec = _StageRecorder()
    svc = BacktestService(db=None, kline_cache=None, progress_manager=rec)
    svc._emit_stage("run1", "loading_signals", "Loading", detail="d", pct=0)
    svc._emit_stage("run1", "complete", "Done", pct=100, status="done")
    assert [e["stage"] for e in rec.events] == ["loading_signals", "complete"]
    assert rec.events[-1]["status"] == "done"


@pytest.mark.asyncio
async def test_service_emit_noop_without_manager():
    """No manager wired → _emit_stage is a safe no-op (the MCP/test path)."""
    from backend.services.backtest_service import BacktestService

    svc = BacktestService(db=None, kline_cache=None)  # no progress_manager
    # Must not raise.
    svc._emit_stage("run1", "loading_signals", "Loading")


@pytest.mark.asyncio
async def test_service_emit_swallows_manager_errors():
    """A throwing manager must not break the run path."""
    from backend.services.backtest_service import BacktestService

    class _Boom:
        def emit(self, *a, **k):
            raise RuntimeError("boom")

    svc = BacktestService(db=None, kline_cache=None, progress_manager=_Boom())
    svc._emit_stage("run1", "loading_signals", "Loading")  # swallowed, no raise
