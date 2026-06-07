"""Tests for the audit hash-chain core — TASK-P0-08 (AC-021)."""
from __future__ import annotations

import pytest


def test_entry_hash_links_chain():
    from backend.mcp.core.audit import compute_entry_hash

    h1 = compute_entry_hash(seq=1, prev_hash=None, payload={"tool": "scans_list", "status": "ok"})
    h2 = compute_entry_hash(seq=2, prev_hash=h1, payload={"tool": "scans_get", "status": "ok"})
    assert h1 != h2
    assert len(h1) == 64  # sha256 hex


def test_verify_chain_detects_tamper():
    from backend.mcp.core.audit import compute_entry_hash, verify_chain

    rows = []
    prev = None
    for i in range(1, 4):
        payload = {"tool": f"t{i}", "status": "ok"}
        h = compute_entry_hash(seq=i, prev_hash=prev, payload=payload)
        rows.append({"seq": i, "prev_hash": prev, "entry_hash": h, "payload": payload})
        prev = h
    assert verify_chain(rows) is True
    # tamper a middle row's payload
    rows[1]["payload"]["status"] = "error"
    assert verify_chain(rows) is False


def test_verify_chain_detects_broken_link():
    from backend.mcp.core.audit import compute_entry_hash, verify_chain

    h1 = compute_entry_hash(seq=1, prev_hash=None, payload={"a": 1})
    rows = [
        {"seq": 1, "prev_hash": None, "entry_hash": h1, "payload": {"a": 1}},
        # prev_hash deliberately wrong (fork)
        {"seq": 2, "prev_hash": "deadbeef", "entry_hash": "x", "payload": {"a": 2}},
    ]
    assert verify_chain(rows) is False


def test_hash_is_over_canonical_payload_order_independent():
    from backend.mcp.core.audit import compute_entry_hash

    a = compute_entry_hash(seq=1, prev_hash=None, payload={"x": 1, "y": 2})
    b = compute_entry_hash(seq=1, prev_hash=None, payload={"y": 2, "x": 1})
    assert a == b  # canonical (sorted-key) serialization


@pytest.mark.asyncio
async def test_audit_writer_serializes_and_chains():
    from backend.mcp.core.audit import AuditWriter

    persisted: list[dict] = []

    class FakeRepo:
        async def last_chain(self):
            if not persisted:
                return (0, None)
            last = persisted[-1]
            return (last["seq"], last["entry_hash"])

        async def append(self, record):
            persisted.append(record)

    writer = AuditWriter(FakeRepo())
    await writer.start()
    try:
        await writer.enqueue({"tool_name": "scans_list", "status": "ok"})
        await writer.enqueue({"tool_name": "scans_get", "status": "ok"})
        await writer.drain()
    finally:
        await writer.shutdown()

    assert [r["seq"] for r in persisted] == [1, 2]
    assert persisted[0]["prev_hash"] is None
    assert persisted[1]["prev_hash"] == persisted[0]["entry_hash"]
    # chain verifies
    from backend.mcp.core.audit import verify_chain

    assert verify_chain(
        [{**r, "payload": r["audit_payload"]} for r in persisted]
    )
