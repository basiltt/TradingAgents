"""Control-plane router + mount tests — TASK-P0-03/12.

Builds a minimal FastAPI app with register_mcp + a real DB-backed MCPManager and
exercises the control-plane endpoints through the dispatch pipeline.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class _DB:
    def __init__(self, pool):
        self.pool = pool

    async def list_scans(self):
        return []


@pytest.fixture
def app_with_mcp(mcp_pool):
    from backend.mcp.mount import MCPManager, register_mcp

    app = FastAPI()
    app.state.db = _DB(mcp_pool)
    register_mcp(app)
    # build manager directly (no full lifespan)
    app.state.mcp_manager = MCPManager(app)
    return app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_mcp_reads_nothing():
    """register_mcp must not touch the DB or build services."""
    from backend.mcp.mount import register_mcp

    app = FastAPI()
    register_mcp(app)
    assert app.state.mcp_asgi is None
    assert app.state.mcp_server is None
    assert app.state.mcp_manager is None
    # the indirection mount + control router are installed
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mcp/rpc" in paths or any("/mcp/rpc" in str(r) for r in app.routes)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_503_when_module_absent():
    app = FastAPI()
    from backend.mcp.mount import register_mcp

    register_mcp(app)  # manager is None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/mcp/status")
    assert r.status_code == 503


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_200_when_off(app_with_mcp):
    await app_with_mcp.state.mcp_manager.boot()
    transport = ASGITransport(app=app_with_mcp)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/mcp/health")
    assert r.status_code == 200
    assert r.json()["state"] == "off"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enable_flow_token_then_groups_then_enable(app_with_mcp):
    await app_with_mcp.state.mcp_manager.boot()
    transport = ASGITransport(app=app_with_mcp)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # generate a token (required by preflight)
        rt = await client.post("/api/v1/mcp/token/regenerate")
        assert rt.status_code == 200 and rt.json()["token"]

        # enable scans group
        cfg = (await client.get("/api/v1/mcp/config")).json()
        rp = await client.patch(
            "/api/v1/mcp/config",
            json={"enabled_groups": ["scans"], "expected_row_version": cfg["row_version"]},
        )
        assert rp.status_code == 200

        # enable the feature (preflight passes)
        re = await client.post("/api/v1/mcp/enable")
        assert re.status_code == 200, re.text

        # status reports running with scans_list advertised
        rs = await client.get("/api/v1/mcp/status")
        assert rs.json()["state"] == "running"
        rtools = await client.get("/api/v1/mcp/tools")
        assert "scans_list" in rtools.json()["tools"]

        # disable
        rd = await client.post("/api/v1/mcp/disable")
        assert rd.status_code == 200
        rs2 = await client.get("/api/v1/mcp/status")
        assert rs2.json()["state"] == "off"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enable_refused_without_token(app_with_mcp):
    await app_with_mcp.state.mcp_manager.boot()
    transport = ASGITransport(app=app_with_mcp)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # no token set -> preflight fails -> 422
        re = await client.post("/api/v1/mcp/enable")
    assert re.status_code == 422
    assert "token" in str(re.json()).lower()
