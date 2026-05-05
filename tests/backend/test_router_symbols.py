"""Tests for symbols router — Phase 2 API tests."""

import pytest
import pytest_asyncio
from unittest.mock import patch
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
async def test_list_symbols_crypto(client):
    with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT", "ETHUSDT", "ADAUSDT"]):
        resp = await client.get("/api/v1/symbols?asset_type=crypto")
    assert resp.status_code == 200
    assert resp.json()["symbols"] == ["ADAUSDT", "BTCUSDT", "ETHUSDT"]


@pytest.mark.asyncio
async def test_list_symbols_stock_returns_empty(client):
    resp = await client.get("/api/v1/symbols?asset_type=stock")
    assert resp.status_code == 200
    assert resp.json()["symbols"] == []


@pytest.mark.asyncio
async def test_list_symbols_invalid_asset_type(client):
    resp = await client.get("/api/v1/symbols?asset_type=forex")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_symbols_default_is_crypto(client):
    with patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT"]):
        resp = await client.get("/api/v1/symbols")
    assert resp.status_code == 200
    assert resp.json()["symbols"] == ["BTCUSDT"]
