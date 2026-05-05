"""Tests for checkpoints router — TASK-007."""

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
async def test_get_checkpoint(client):
    resp = await client.get("/api/v1/checkpoints?ticker=SPY&date=2025-06-01")
    assert resp.status_code == 200
    data = resp.json()
    assert "exists" in data


@pytest.mark.asyncio
async def test_delete_checkpoints_without_confirm(client):
    resp = await client.delete(
        "/api/v1/checkpoints",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_checkpoints_with_confirm(client):
    resp = await client.delete(
        "/api/v1/checkpoints?confirm=true",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_ticker_checkpoints_without_confirm(client):
    resp = await client.delete(
        "/api/v1/checkpoints/SPY",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_ticker_checkpoints_with_confirm(client):
    resp = await client.delete(
        "/api/v1/checkpoints/SPY?confirm=true",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_get_checkpoint_invalid_ticker(client):
    resp = await client.get("/api/v1/checkpoints?ticker=../../../etc&date=2025-06-01")
    assert resp.status_code == 400
