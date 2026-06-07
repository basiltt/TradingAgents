"""scans_list tool tests — TASK-P0-13 (AC-017 no-side-effect read)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch


class _FakeServices:
    def __init__(self, db):
        self.db = db


class _FakeDB:
    def __init__(self):
        self.list_scans_calls = 0
        self.run_scan_calls = 0

    async def list_scans(self):
        self.list_scans_calls += 1
        return [
            {"scan_id": "s1", "status": "completed", "total": 10, "completed": 9,
             "failed": 1, "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            {"scan_id": "s2", "status": "running", "total": 5, "completed": 2,
             "failed": 0, "started_at": None},
        ]

    async def run_scan(self, *a, **k):  # must NOT be called by a read tool
        self.run_scan_calls += 1


def _ctx(db):
    return CallContext(
        principal="t", session_id="s", tier="READ_ONLY", correlation_id=None,
        services=_FakeServices(db), clock=RealClock(),
    )


@pytest.mark.asyncio
async def test_scans_list_returns_summaries_without_running_scanner():
    from backend.mcp.core.registry import _REGISTRY
    from backend.mcp.tools.scans import list_scans  # noqa: F401 — registers the tool

    db = _FakeDB()
    spec = _REGISTRY["scans_list"]
    audited = []
    result = await dispatch(spec, {"limit": 20}, _ctx(db), audit=audited.append)
    assert result["isError"] is False
    assert result["structuredContent"]["count"] == 2
    assert result["structuredContent"]["scans"][0]["scan_id"] == "s1"
    # the scanner was never invoked (no side effects)
    assert db.list_scans_calls == 1
    assert db.run_scan_calls == 0
    assert audited[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_scans_list_respects_limit():
    from backend.mcp.core.registry import _REGISTRY
    from backend.mcp.tools.scans import list_scans  # noqa: F401

    db = _FakeDB()
    spec = _REGISTRY["scans_list"]
    result = await dispatch(spec, {"limit": 1}, _ctx(db), audit=lambda r: None)
    assert result["structuredContent"]["count"] == 1


@pytest.mark.asyncio
async def test_scans_list_service_unavailable():
    from backend.mcp.core.registry import _REGISTRY
    from backend.mcp.tools.scans import list_scans  # noqa: F401

    spec = _REGISTRY["scans_list"]
    audited = []
    result = await dispatch(spec, {"limit": 20}, _ctx(None), audit=audited.append)
    assert result["isError"] is True
    assert audited[0]["status"] == "error"
