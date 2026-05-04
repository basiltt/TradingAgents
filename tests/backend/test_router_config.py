"""Tests for config router — TASK-007."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app(tmp_path):
    import os
    os.environ["TRADINGAGENTS_WEB_DB_PATH"] = str(tmp_path / "test.db")
    from backend.main import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


@pytest.mark.asyncio
async def test_get_config(client):
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "defaults" in data
    assert "resolved" in data


@pytest.mark.asyncio
async def test_patch_config_valid(client):
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"output_language": "Japanese"}},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert resp.json()["overrides"]["output_language"] == "Japanese"


@pytest.mark.asyncio
async def test_patch_config_unknown_key(client):
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"nonexistent": "value"}},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 500 or resp.status_code == 422 or resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_llm_concurrency(client):
    from unittest.mock import patch as mpatch
    with mpatch("backend.routers.config.configure_llm_concurrency") as mock_cfg:
        resp = await client.patch(
            "/api/v1/config",
            json={"overrides": {"llm_max_concurrent": 4}},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 200
    mock_cfg.assert_called_once_with(4)
