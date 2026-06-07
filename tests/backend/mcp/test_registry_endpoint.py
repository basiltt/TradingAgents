"""Enriched control-plane registry endpoint tests — P2 budget manager.

GET /api/v1/mcp/registry returns the FULL tool catalog (every registered tool,
not just the currently-enabled ones) annotated with token cost + enabled/
available state, so the operator UI can render the context-budget manager even
while the server is OFF. This is the P2 enrichment of the P0 /mcp/tools stub.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def app_with_mcp(mcp_pool):
    from fastapi import FastAPI

    from backend.mcp.mount import MCPManager, register_mcp

    class _DB:
        def __init__(self, pool):
            self.pool = pool

        async def list_scans(self):
            return []

    app = FastAPI()
    app.state.db = _DB(mcp_pool)
    register_mcp(app)
    mgr = MCPManager(app)
    app.state.mcp_manager = mgr
    await mgr.boot()
    yield app, mgr
    await mgr.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_lists_all_tools_with_budget(app_with_mcp):
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/mcp/registry")
    assert r.status_code == 200
    body = r.json()
    # full catalog present even though nothing is enabled yet
    assert len(body["tools"]) > 0
    names = {t["name"] for t in body["tools"]}
    assert "scans_list" in names
    for t in body["tools"]:
        assert {"name", "group", "safety_class", "est_tokens", "enabled", "available", "mutating"} <= t.keys()
        assert isinstance(t["est_tokens"], int) and t["est_tokens"] > 0
    # group rollup + total + presets
    assert body["total_est_tokens"] == sum(t["est_tokens"] for t in body["tools"])
    assert "scans" in body["groups"]
    assert body["groups"]["scans"]["est_tokens"] > 0
    assert set(body["presets"].keys()) >= {"minimal", "read_only", "backtest_only", "standard", "full"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_reflects_enabled_groups(app_with_mcp):
    app, mgr = app_with_mcp
    cfg = await mgr.config_repo.get()
    await mgr.config_repo.update({"enabled_groups": ["scans"]}, expected_row_version=cfg.row_version)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/mcp/registry")
    body = r.json()
    scans = [t for t in body["tools"] if t["group"] == "scans"]
    others = [t for t in body["tools"] if t["group"] not in ("scans",)]
    assert scans and all(t["enabled"] for t in scans)
    # a tool in a non-enabled group should not be enabled
    assert any(not t["enabled"] for t in others)
    # selected budget = sum of enabled tools
    assert body["selected_est_tokens"] == sum(t["est_tokens"] for t in body["tools"] if t["enabled"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apply_preset_endpoint_sets_groups(app_with_mcp):
    app, mgr = app_with_mcp
    cfg = await mgr.config_repo.get()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/mcp/registry/preset",
            json={"preset": "backtest_only", "expected_row_version": cfg.row_version},
        )
    assert r.status_code == 200
    body = r.json()
    # backtest_only selects backtest + optimizer + read-only groups via per-tool overrides
    enabled_names = {t["name"] for t in body["tools"] if t["enabled"]}
    assert "backtest_run" in enabled_names
    # an unknown preset is a 422
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg2 = await mgr.config_repo.get()
        bad = await client.post(
            "/api/v1/mcp/registry/preset",
            json={"preset": "does_not_exist", "expected_row_version": cfg2.row_version},
        )
    assert bad.status_code == 422
