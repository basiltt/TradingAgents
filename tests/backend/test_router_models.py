"""Tests for models router — TASK-007."""

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
async def test_get_models_valid_provider(client):
    resp = await client.get("/api/v1/models/openai")
    assert resp.status_code == 200
    data = resp.json()
    assert "quick" in data
    assert "deep" in data


@pytest.mark.asyncio
async def test_get_models_invalid_provider(client):
    resp = await client.get("/api/v1/models/badprovider")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_providers(client):
    resp = await client.get("/api/v1/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "openai" in data["providers"]
    assert "anthropic" in data["providers"]
