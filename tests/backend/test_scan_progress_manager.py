"""Tests for ScanProgressManager — the post-scan auto-trade progress pub/sub (TASK-1.1)."""
import asyncio

import pytest

from backend.services.scan_progress_manager import ScanProgressManager


@pytest.mark.asyncio
async def test_emit_then_subscribe_replays_history():
    mgr = ScanProgressManager()
    mgr.emit("scan-1", "init_balances", "Loading balances", status="active")
    mgr.emit("scan-1", "execute_batch", "Placing batch", status="active")
    q = mgr.subscribe("scan-1")
    # History is pre-loaded for a late subscriber.
    ev1 = q.get_nowait()
    ev2 = q.get_nowait()
    assert ev1["stage"] == "init_balances"
    assert ev2["stage"] == "execute_batch"
    assert ev1["type"] == "scan_auto_trade_progress"
    mgr.unsubscribe("scan-1", q)


@pytest.mark.asyncio
async def test_live_event_reaches_subscriber():
    mgr = ScanProgressManager()
    q = mgr.subscribe("scan-2")
    mgr.emit("scan-2", "execute_batch", "Placing", status="active",
             account_id="A", symbol="BTCUSDT", side="buy")
    ev = q.get_nowait()
    assert ev["account_id"] == "A"
    assert ev["symbol"] == "BTCUSDT"
    assert ev["side"] == "buy"
    mgr.unsubscribe("scan-2", q)


@pytest.mark.asyncio
async def test_monotonic_seq_per_scan():
    mgr = ScanProgressManager()
    e1 = mgr.emit("s", "a", "A")
    e2 = mgr.emit("s", "b", "B")
    e3 = mgr.emit("s", "c", "C")
    assert e1["seq"] < e2["seq"] < e3["seq"]


@pytest.mark.asyncio
async def test_multiple_subscribers_independent():
    mgr = ScanProgressManager()
    q1 = mgr.subscribe("s")
    q2 = mgr.subscribe("s")
    mgr.emit("s", "a", "A")
    assert q1.get_nowait()["stage"] == "a"
    assert q2.get_nowait()["stage"] == "a"


@pytest.mark.asyncio
async def test_bounded_queue_drops_oldest_not_blocks_emitter():
    mgr = ScanProgressManager()
    q = mgr.subscribe("s")
    # Fill far past the queue maxsize; emit must never block / raise.
    for i in range(1000):
        mgr.emit("s", f"stage{i}", "x")
    # The subscriber queue retained at most its maxsize (drop-oldest).
    assert q.qsize() <= 256


@pytest.mark.asyncio
async def test_terminal_event_and_history_methods():
    mgr = ScanProgressManager()
    mgr.emit("s", "execute_batch", "x", status="active")
    mgr.emit("s", "complete", "Done", status="done")
    hist = mgr.history("s")
    assert hist[-1]["stage"] == "complete"
    assert hist[-1]["status"] == "done"


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    mgr = ScanProgressManager()
    q = mgr.subscribe("s")
    mgr.unsubscribe("s", q)
    # After unsubscribe, an emit does not reach the old queue.
    mgr.emit("s", "a", "A")
    assert q.empty()


def test_emit_never_raises_on_no_subscribers():
    mgr = ScanProgressManager()
    # No subscribers — emit is a safe no-op fan-out (history still recorded).
    ev = mgr.emit("nobody", "a", "A")
    assert ev["scan_id"] == "nobody"
    assert mgr.history("nobody")[0]["stage"] == "a"


def test_event_payload_keeps_account_id_server_side():
    """The manager event carries account_id (for server correlation); the WS
    boundary strips it. Here we just confirm the field exists for the recorder."""
    mgr = ScanProgressManager()
    ev = mgr.emit("s", "execute_batch", "x", account_id="acct-raw", acct_ordinal=2)
    assert ev["account_id"] == "acct-raw"
    assert ev["acct_ordinal"] == 2
    # Free-text label must NOT be on the event payload (no leak).
    assert "label" not in ev


def test_subscribe_late_joiner_gets_terminal_event_on_long_scan():
    """A late subscriber to a scan whose history exceeds the queue capacity must
    still receive the NEWEST events incl. the terminal one (newest-biased replay)."""
    mgr = ScanProgressManager()
    for i in range(400):
        mgr.emit("s", f"stage{i}", "x", status="active")
    mgr.emit("s", "complete", "Done", status="done")
    q = mgr.subscribe("s")
    drained = []
    while not q.empty():
        drained.append(q.get_nowait())
    # The terminal event is present despite the long history.
    assert drained[-1]["stage"] == "complete"
    assert drained[-1]["status"] == "done"


def test_drop_oldest_keeps_newest_exactly():
    mgr = ScanProgressManager()
    q = mgr.subscribe("s")
    for i in range(1000):
        mgr.emit("s", f"stage{i}", "x")
    # Queue holds exactly its max, newest retained, oldest dropped.
    assert q.qsize() == 256
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert items[-1]["stage"] == "stage999"
    assert items[0]["stage"] == "stage744"


def test_terminal_gc_purges_after_retention(monkeypatch):
    import backend.services.scan_progress_manager as m
    mgr = m.ScanProgressManager()
    t = [1000.0]
    monkeypatch.setattr(m.time, "time", lambda: t[0])
    mgr.emit("A", "complete", "x", status="done")
    assert mgr.history("A")
    # Advance past terminal retention, then emit on B to trigger gc.
    t[0] = 1000.0 + m._TERMINAL_RETENTION_S + 1
    mgr.emit("B", "execute_batch", "x")
    assert mgr.history("A") == []
    assert mgr.history("B")


def test_idle_gc_purges_abandoned_non_terminal_scan(monkeypatch):
    import backend.services.scan_progress_manager as m
    mgr = m.ScanProgressManager()
    t = [1000.0]
    monkeypatch.setattr(m.time, "time", lambda: t[0])
    mgr.emit("A", "execute_batch", "x", status="active")  # never reaches terminal
    # Advance past idle retention, emit on B to trigger gc.
    t[0] = 1000.0 + m._IDLE_RETENTION_S + 1
    mgr.emit("B", "execute_batch", "x")
    assert mgr.history("A") == []  # abandoned scan GC'd by idle age


def test_history_truncation_keeps_terminal():
    import backend.services.scan_progress_manager as m
    mgr = m.ScanProgressManager()
    for i in range(m._MAX_HISTORY + 50):
        mgr.emit("s", f"stage{i}", "x", status="active")
    mgr.emit("s", "complete", "Done", status="done")
    hist = mgr.history("s")
    assert len(hist) == m._MAX_HISTORY
    assert hist[-1]["stage"] == "complete"


def test_terminal_at_only_for_real_terminal():
    import backend.services.scan_progress_manager as m
    mgr = m.ScanProgressManager()
    mgr.emit("s", "execute_batch", "x", status="done")  # done but not a terminal stage
    assert "s" not in mgr._terminal_at
    mgr.emit("s", "complete", "x", status="done")
    assert "s" in mgr._terminal_at

