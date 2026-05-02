"""Tests for memory router — TASK-007."""

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
async def test_get_memory(client):
    resp = await client.get("/api/v1/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_memory_pagination(client):
    resp = await client.get("/api/v1/memory?page=1&limit=10")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_memory_invalid_limit(client):
    resp = await client.get("/api/v1/memory?limit=0")
    assert resp.status_code == 422
