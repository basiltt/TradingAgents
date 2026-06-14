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
