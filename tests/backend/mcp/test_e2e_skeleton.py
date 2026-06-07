"""P0 walking-skeleton e2e — TASK-P0 exit criterion.

Drives MCPServer (the in-process bridge) through initialize -> tools/list ->
tools/call(scans_list), asserting the dispatch pipeline + single audit writer
work end to end and emit exactly one audit row. No socket/transport required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.mcp.core.audit import AuditWriter
from backend.mcp.core.registry import MCPConfigView
from backend.mcp.core.server import MCPServer, negotiate_protocol


class _FakeDB:
    async def list_scans(self):
        return [
            {"scan_id": "s1", "status": "completed", "total": 3, "completed": 3,
             "failed": 0, "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        ]


class _AppState:
    db = _FakeDB()


class _CollectingRepo:
    def __init__(self):
        self.rows = []

    async def last_chain(self):
        if not self.rows:
            return (0, None)
        last = self.rows[-1]
        return (last["seq"], last["entry_hash"])

    async def append(self, record):
        self.rows.append(record)


def test_negotiate_protocol_down_negotiates():
    assert negotiate_protocol(None) == "2025-06-18"
    assert negotiate_protocol("2025-03-26") == "2025-03-26"
    assert negotiate_protocol("1999-01-01") == "2025-06-18"  # unsupported -> ceiling


@pytest.mark.asyncio
async def test_initialize_list_call_emits_one_audit_row():
    repo = _CollectingRepo()
    writer = AuditWriter(repo)
    await writer.start()

    cfg = MCPConfigView(
        capability_tier="READ_ONLY",
        enabled_groups=["scans"],
        enabled_tools={},
    )
    server = MCPServer(
        config_view=cfg,
        app_state=_AppState(),
        audit_writer=writer,
    )
    try:
        # initialize
        init = server.initialize(requested_protocol="2025-06-18")
        assert init["serverInfo"]["name"] == "tradingagents-mcp"
        assert init["capabilities"]["tools"]["listChanged"] is True

        # tools/list -> only scans_list advertised (READ_ONLY tier, scans group)
        tools = server.list_tools()
        names = {t["name"] for t in tools}
        assert "scans_list" in names
        # annotations present
        sl = next(t for t in tools if t["name"] == "scans_list")
        assert sl["annotations"]["readOnlyHint"] is True

        # tools/call
        result = await server.call_tool(
            "scans_list", {"limit": 10}, principal="tok", session_id="sess"
        )
        assert result["isError"] is False
        assert result["structuredContent"]["count"] == 1

        # let the fire-and-forget audit enqueue + writer drain
        await asyncio.sleep(0)
        await writer.drain()
    finally:
        await server.shutdown()

    # exactly one audit row for the one tool call, status ok
    assert len(repo.rows) == 1
    assert repo.rows[0]["tool_name"] == "scans_list"
    assert repo.rows[0]["status"] == "ok"
    assert repo.rows[0]["seq"] == 1


@pytest.mark.asyncio
async def test_disabled_tool_call_is_method_not_found():
    repo = _CollectingRepo()
    writer = AuditWriter(repo)
    await writer.start()
    cfg = MCPConfigView(capability_tier="READ_ONLY", enabled_groups=[], enabled_tools={})
    server = MCPServer(config_view=cfg, app_state=_AppState(), audit_writer=writer)
    try:
        # scans group not enabled -> scans_list not advertised, call -> -32601
        assert all(t["name"] != "scans_list" for t in server.list_tools())
        result = await server.call_tool("scans_list", {}, principal="t", session_id="s")
        assert result["isError"] is True
        assert result["code"] == -32601
    finally:
        await server.shutdown()
