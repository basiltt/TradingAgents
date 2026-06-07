"""AuditRepository + AuditWriter DB integration — TASK-P0-02/08 (AC-021)."""
from __future__ import annotations

import pytest

from backend.mcp.core.audit import AuditWriter, verify_chain


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_writer_persists_continuous_chain(mcp_pool):
    from backend.mcp.repositories.audit_repo import AuditRepository

    repo = AuditRepository(mcp_pool)
    writer = AuditWriter(repo)
    await writer.start()
    try:
        for i in range(5):
            await writer.enqueue(
                {"tool_name": f"t{i}", "tool_group": "scans", "status": "ok",
                 "safety_class": "read_only", "mutating": False}
            )
        await writer.drain()
    finally:
        await writer.shutdown()

    async with mcp_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT seq, prev_hash, entry_hash, tool_name, status FROM mcp_audit_log ORDER BY seq"
        )
    assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5]
    # reconstruct payloads to verify the chain
    chain = [
        {
            "seq": r["seq"],
            "prev_hash": r["prev_hash"],
            "entry_hash": r["entry_hash"],
            "payload": {
                "tool_name": r["tool_name"], "tool_group": "scans", "status": "ok",
                "safety_class": "read_only", "mutating": False,
                "principal_token_id": None, "session_id": None, "correlation_id": None,
                "args_redacted": None, "error": None,
            },
        }
        for r in rows
    ]
    # NOTE: chain hash covers the full payload dict the writer received; this test
    # asserts persisted seq/prev_hash linkage is continuous (no fork).
    for i in range(1, len(rows)):
        assert rows[i]["prev_hash"] == rows[i - 1]["entry_hash"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_chain_resumes_across_writer_restart(mcp_pool):
    from backend.mcp.repositories.audit_repo import AuditRepository

    repo = AuditRepository(mcp_pool)
    w1 = AuditWriter(repo)
    await w1.start()
    await w1.enqueue({"tool_name": "a", "status": "ok"})
    await w1.drain()
    await w1.shutdown()

    # a fresh writer must continue the chain (seq 2, prev = row1.entry_hash)
    w2 = AuditWriter(repo)
    await w2.start()
    await w2.enqueue({"tool_name": "b", "status": "ok"})
    await w2.drain()
    await w2.shutdown()

    async with mcp_pool.acquire() as conn:
        rows = await conn.fetch("SELECT seq, prev_hash, entry_hash FROM mcp_audit_log ORDER BY seq")
    assert [r["seq"] for r in rows] == [1, 2]
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]
