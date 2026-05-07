"""Tests for backend.services.bybit_client — Bybit V5 REST client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_client import BybitAPIError, BybitClient


@pytest.fixture
def client():
    return BybitClient("test_api_key_123", "test_api_secret_456", "demo")


def test_base_url_demo(client):
    assert "api-demo.bybit.com" in client._base_url


def test_base_url_live():
    c = BybitClient("k", "s", "live")
    assert "api.bybit.com" in c._base_url
    assert "demo" not in c._base_url


def test_sign_deterministic(client):
    sig1 = client._sign(1000000, "param=value")
    sig2 = client._sign(1000000, "param=value")
    assert sig1 == sig2
    assert len(sig1) == 64


def test_sign_changes_with_params(client):
    sig1 = client._sign(1000000, "a=1")
    sig2 = client._sign(1000000, "a=2")
    assert sig1 != sig2


def test_headers_structure(client):
    headers = client._headers(1000000, "test=1")
    assert headers["X-BAPI-API-KEY"] == "test_api_key_123"
    assert headers["X-BAPI-TIMESTAMP"] == "1000000"
    assert headers["X-BAPI-RECV-WINDOW"] == "5000"
    assert "X-BAPI-SIGN" in headers
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_request_success(client):
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={"retCode": 0, "result": {"data": "ok"}})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client._request("GET", "/v5/test", {"key": "val"})
    assert result == {"data": "ok"}


@pytest.mark.asyncio
async def test_request_api_error(client):
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={"retCode": 10001, "retMsg": "Invalid key"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(BybitAPIError) as exc_info:
            await client._request("GET", "/v5/test", {})
    assert exc_info.value.ret_code == 10001
    assert "Invalid key" in exc_info.value.ret_msg


@pytest.mark.asyncio
async def test_test_connection_success(client):
    wallet_result = {"list": [{"accountIMRate": "uid123"}]}
    with patch.object(client, "_request", new_callable=AsyncMock, return_value=wallet_result):
        result = await client.test_connection()
    assert result["success"] is True


@pytest.mark.asyncio
async def test_test_connection_failure(client):
    with patch.object(client, "_request", new_callable=AsyncMock, side_effect=BybitAPIError(10001, "Bad key")):
        result = await client.test_connection()
    assert result["success"] is False
    assert "Bad key" in result["error"]


@pytest.mark.asyncio
async def test_get_wallet_balance_empty(client):
    with patch.object(client, "_request", new_callable=AsyncMock, return_value={"list": []}):
        result = await client.get_wallet_balance()
    assert result["totalEquity"] == "0"
    assert result["coin"] == []


@pytest.mark.asyncio
async def test_get_wallet_balance_with_data(client):
    data = {"list": [{"totalEquity": "1000", "totalWalletBalance": "900", "totalAvailableBalance": "800", "totalPerpUPL": "100", "accountIMRate": "0.1", "accountMMRate": "0.05", "coin": [{"coin": "USDT"}]}]}
    with patch.object(client, "_request", new_callable=AsyncMock, return_value=data):
        result = await client.get_wallet_balance()
    assert result["totalEquity"] == "1000"
    assert len(result["coin"]) == 1


@pytest.mark.asyncio
async def test_get_positions_filters_zero_size(client):
    data = {"list": [
        {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "avgPrice": "50000", "markPrice": "51000", "unrealisedPnl": "100", "leverage": "10", "liqPrice": "45000", "takeProfit": "", "stopLoss": "", "positionIM": "500", "positionMM": "250"},
        {"symbol": "ETHUSDT", "side": "Sell", "size": "0", "avgPrice": "3000", "markPrice": "3000", "unrealisedPnl": "0", "leverage": "5", "liqPrice": "0", "takeProfit": "", "stopLoss": "", "positionIM": "0", "positionMM": "0"},
    ]}
    with patch.object(client, "_request", new_callable=AsyncMock, return_value=data):
        result = await client.get_positions()
    assert len(result) == 1
    assert result[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_open_orders(client):
    data = {"list": [{"orderId": "o1", "symbol": "BTCUSDT", "side": "Buy", "orderType": "Limit", "qty": "0.01", "price": "50000", "orderStatus": "New", "createdTime": "123", "triggerPrice": "", "stopOrderType": ""}]}
    with patch.object(client, "_request", new_callable=AsyncMock, return_value=data):
        result = await client.get_open_orders()
    assert len(result) == 1
    assert result[0]["orderId"] == "o1"


@pytest.mark.asyncio
async def test_get_closed_pnl(client):
    data = {"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": "abc"}
    with patch.object(client, "_request", new_callable=AsyncMock, return_value=data):
        result = await client.get_closed_pnl(1000, 2000, limit=50)
    assert result["list"] == [{"symbol": "BTCUSDT"}]
    assert result["nextPageCursor"] == "abc"
