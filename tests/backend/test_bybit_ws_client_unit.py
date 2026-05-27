"""Unit tests for BybitWSClient — auth payload, message handling, emit helpers."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.bybit_ws_client import (
    BybitWSClient,
    _WS_ENDPOINTS,
    _RECONNECT_BASE,
    _RECONNECT_MAX,
    _PING_INTERVAL,
    _PONG_TIMEOUT,
)


@pytest.fixture
def on_event():
    return AsyncMock()


@pytest.fixture
def client(on_event):
    return BybitWSClient("api_key", "api_secret", "demo", on_event, account_id="acc1")


class TestInit:
    def test_demo_url(self, on_event):
        c = BybitWSClient("k", "s", "demo", on_event)
        assert c._url == _WS_ENDPOINTS["demo"]

    def test_live_url(self, on_event):
        c = BybitWSClient("k", "s", "live", on_event)
        assert c._url == _WS_ENDPOINTS["live"]

    def test_unknown_defaults_demo(self, on_event):
        c = BybitWSClient("k", "s", "unknown", on_event)
        assert c._url == _WS_ENDPOINTS["demo"]


class TestAuthPayload:
    def test_has_required_fields(self, client):
        payload = client._auth_payload()
        assert payload["op"] == "auth"
        assert len(payload["args"]) == 3
        assert payload["args"][0] == "api_key"

    def test_signature_is_hex(self, client):
        payload = client._auth_payload()
        sig = payload["args"][2]
        assert all(c in "0123456789abcdef" for c in sig)


class TestSubscribePayload:
    def test_subscribes_to_channels(self, client):
        payload = client._subscribe_payload()
        assert payload["op"] == "subscribe"
        assert "wallet" in payload["args"]
        assert "position" in payload["args"]
        assert "order" in payload["args"]
        assert "execution" in payload["args"]


class TestHandleMessage:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_pong_ignored(self, client, on_event):
        await client._handle_message(json.dumps({"op": "pong"}))
        on_event.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_pong_ret_msg_ignored(self, client, on_event):
        await client._handle_message(json.dumps({"ret_msg": "pong"}))
        on_event.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_topic_ignored(self, client, on_event):
        await client._handle_message(json.dumps({"data": []}))
        on_event.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_data_ignored(self, client, on_event):
        await client._handle_message(json.dumps({"topic": "wallet", "data": []}))
        on_event.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_json_ignored(self, client, on_event):
        await client._handle_message("not json")
        on_event.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_wallet_message(self, client, on_event):
        msg = {"topic": "wallet", "data": [{"accountEquity": "1000", "coin": []}]}
        await client._handle_message(json.dumps(msg))
        on_event.assert_awaited_once()
        event = on_event.call_args[0][0]
        assert event["type"] == "wallet_update"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_position_message(self, client, on_event):
        msg = {"topic": "position", "data": [{"symbol": "BTCUSDT", "side": "Buy", "size": "1"}]}
        await client._handle_message(json.dumps(msg))
        event = on_event.call_args[0][0]
        assert event["type"] == "position_update"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_execution_message(self, client, on_event):
        msg = {"topic": "execution", "data": [{"symbol": "BTCUSDT", "side": "Buy"}]}
        await client._handle_message(json.dumps(msg))
        event = on_event.call_args[0][0]
        assert event["type"] == "execution"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_order_message(self, client, on_event):
        msg = {"topic": "order", "data": [{"orderId": "123", "symbol": "BTCUSDT"}]}
        await client._handle_message(json.dumps(msg))
        event = on_event.call_args[0][0]
        assert event["type"] == "order_update"


class TestSafeEmit:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_callback_error_caught(self, client, on_event):
        on_event.side_effect = Exception("callback crash")
        await client._safe_emit({"type": "test"})

    @pytest.mark.asyncio(loop_scope="function")
    async def test_callback_success(self, client, on_event):
        await client._safe_emit({"type": "test"})
        on_event.assert_awaited_once()


class TestStartStop:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_idempotent(self, client):
        with patch.object(client, "_run_loop", new_callable=AsyncMock):
            await client.start()
            task1 = client._task
            await client.start()
            assert client._task is task1
            await client.stop()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stop_without_start(self, client):
        await client.stop()
        assert client._running is False


class TestEmitWallet:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_wallet_upl_sum(self, client, on_event):
        data = [{"totalEquity": "5000", "totalPerpUPL": "150.0", "totalWalletBalance": "4850", "coin": [
            {"unrealisedPnl": "100"}, {"unrealisedPnl": "50"},
        ]}]
        await client._emit_wallet(data)
        event = on_event.call_args[0][0]
        assert event["data"]["totalPerpUPL"] == "150.0"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_wallet_bad_upl_skipped(self, client, on_event):
        data = [{"totalEquity": "5000", "totalPerpUPL": "50.0", "totalWalletBalance": "4950", "coin": [
            {"unrealisedPnl": "bad"}, {"unrealisedPnl": "50"},
        ]}]
        await client._emit_wallet(data)
        event = on_event.call_args[0][0]
        assert event["data"]["totalPerpUPL"] == "50.0"
