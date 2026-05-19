"""Comprehensive unit tests for BybitClient."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from backend.services.bybit_client import (
    BybitAPIError,
    BybitClient,
    _MAX_RETRIES,
    _RATE_LIMIT_MAX,
    _RATE_LIMIT_WINDOW,
    _RETRY_BASE_DELAY,
)


@pytest.fixture
def client() -> BybitClient:
    return BybitClient(api_key="test_key", api_secret="test_secret", account_type="demo")


@pytest.fixture
def live_client() -> BybitClient:
    return BybitClient(api_key="k", api_secret="s", account_type="live")


# --- Initialization ---


class TestInit:
    def test_demo_endpoint(self, client: BybitClient):
        assert client._base_url == "https://api-demo.bybit.com"

    def test_live_endpoint(self, live_client: BybitClient):
        assert live_client._base_url == "https://api.bybit.com"

    def test_unknown_account_type_defaults_to_demo(self):
        c = BybitClient("k", "s", "unknown")
        assert c._base_url == "https://api-demo.bybit.com"

    def test_initial_state(self, client: BybitClient):
        assert client._time_synced is False
        assert client._time_offset_ms == 0
        assert client._session is None


# --- Signature ---


class TestSign:
    def test_sign_produces_correct_hmac(self, client: BybitClient):
        timestamp = 1700000000000
        params_str = "accountType=UNIFIED"
        expected_sign_str = f"{timestamp}test_key5000{params_str}"
        expected = hmac.new(
            b"test_secret", expected_sign_str.encode(), hashlib.sha256
        ).hexdigest()
        assert client._sign(timestamp, params_str) == expected

    def test_headers_structure(self, client: BybitClient):
        headers = client._headers(1700000000000, "foo")
        assert headers["X-BAPI-API-KEY"] == "test_key"
        assert headers["X-BAPI-TIMESTAMP"] == "1700000000000"
        assert headers["X-BAPI-RECV-WINDOW"] == "5000"
        assert "X-BAPI-SIGN" in headers
        assert headers["Content-Type"] == "application/json"


# --- Session management ---


class TestSession:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_session_creates_once(self, client: BybitClient):
        s1 = await client._get_session()
        s2 = await client._get_session()
        assert s1 is s2
        await client.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_sets_session_none(self, client: BybitClient):
        await client._get_session()
        await client.close()
        assert client._session is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_when_no_session(self, client: BybitClient):
        await client.close()  # should not raise


# --- Time sync ---


class TestTimeSync:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_sync_time_success(self, client: BybitClient):
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "result": {"timeNano": "1700000000000000000"}
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.closed = False

        client._session = mock_session
        await client._sync_time()
        assert client._time_synced is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sync_time_failure_logs_warning(self, client: BybitClient):
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("timeout"))
        mock_session.closed = False

        client._session = mock_session
        await client._sync_time()
        assert client._time_synced is False  # stays False on error

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ensure_time_synced_skips_if_fresh(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()  # just synced
        with patch.object(client, "_do_sync_time") as mock_sync:
            await client._ensure_time_synced()
            mock_sync.assert_not_called()


# --- _request method ---


def _make_mock_response(data: dict, status: int = 200, headers: dict | None = None):
    """Create a mock aiohttp response context manager."""
    resp = AsyncMock()
    resp.json = AsyncMock(return_value=data)
    resp.headers = headers or {}
    resp.status = status
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


class TestRequest:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_request_success(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        mock_resp = _make_mock_response({"retCode": 0, "result": {"list": []}})
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("GET", "/v5/test", {"key": "val"})
        assert result == {"list": []}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_post_request_success(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        mock_resp = _make_mock_response({"retCode": 0, "result": {"orderId": "123"}})
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("POST", "/v5/order/create", {"symbol": "BTCUSDT"})
        assert result == {"orderId": "123"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_api_error_raises(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        mock_resp = _make_mock_response({"retCode": 10004, "retMsg": "Invalid param"})
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        client._session = mock_session

        with pytest.raises(BybitAPIError) as exc_info:
            await client._request("GET", "/v5/test", {"k": "v"})
        assert exc_info.value.ret_code == 10004
        assert "Invalid param" in exc_info.value.ret_msg

    @pytest.mark.asyncio(loop_scope="function")
    async def test_network_error_retries(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        fail_resp = AsyncMock()
        fail_resp.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("conn reset"))
        fail_resp.__aexit__ = AsyncMock(return_value=False)

        success_resp = _make_mock_response({"retCode": 0, "result": {"ok": True}})

        mock_session = AsyncMock()
        mock_session.request = MagicMock(side_effect=[fail_resp, success_resp])
        mock_session.closed = False
        client._session = mock_session

        with patch("backend.services.bybit_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/v5/test", {"a": "1"})
        assert result == {"ok": True}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_network_error_no_retry_raises(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        fail_resp = AsyncMock()
        fail_resp.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
        fail_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=fail_resp)
        mock_session.closed = False
        client._session = mock_session

        with pytest.raises(BybitAPIError) as exc_info:
            await client._request("POST", "/v5/order/create", {"s": "1"}, retry_on_network_error=False)
        assert exc_info.value.ret_code == -1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_timestamp_error_resyncs(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        ts_error = _make_mock_response({"retCode": 10002, "retMsg": "timestamp error"})
        success = _make_mock_response({"retCode": 0, "result": {"data": 1}})

        mock_session = AsyncMock()
        mock_session.request = MagicMock(side_effect=[ts_error, success])
        mock_session.closed = False
        client._session = mock_session

        with patch.object(client, "_sync_time", new_callable=AsyncMock):
            result = await client._request("GET", "/v5/test", {"x": "1"})
        assert result == {"data": 1}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_rate_limit_retries(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        rate_resp = _make_mock_response(
            {"retCode": 10006, "retMsg": "rate limit exceeded"},
            headers={"X-Bapi-Limit-Reset-Timestamp": str(int(time.time() * 1000) + 1000)},
        )
        success = _make_mock_response({"retCode": 0, "result": {}})

        mock_session = AsyncMock()
        mock_session.request = MagicMock(side_effect=[rate_resp, success])
        mock_session.closed = False
        client._session = mock_session

        with patch("backend.services.bybit_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/v5/test", {"a": "b"})
        assert result == {}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_rate_limit_exhausted_raises(self, client: BybitClient):
        client._time_synced = True
        client._last_sync_at = time.monotonic()

        rate_resp = _make_mock_response({"retCode": 10006, "retMsg": "rate limit"}, headers={})

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=rate_resp)
        mock_session.closed = False
        client._session = mock_session

        with patch("backend.services.bybit_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(BybitAPIError) as exc_info:
                await client._request("GET", "/v5/test", {"a": "b"})
        assert exc_info.value.ret_code == 10006


# --- _parse_reset_delay_from_headers ---


class TestParseResetDelay:
    def test_valid_header(self):
        now_ms = int(time.time() * 1000)
        headers = {"X-Bapi-Limit-Reset-Timestamp": str(now_ms + 2000)}
        delay = BybitClient._parse_reset_delay_from_headers(headers)
        assert delay is not None
        assert 1.5 < delay < 2.5

    def test_missing_header(self):
        assert BybitClient._parse_reset_delay_from_headers({}) is None

    def test_invalid_header(self):
        assert BybitClient._parse_reset_delay_from_headers({"X-Bapi-Limit-Reset-Timestamp": "bad"}) is None

    def test_past_timestamp_returns_minimum(self):
        now_ms = int(time.time() * 1000)
        headers = {"X-Bapi-Limit-Reset-Timestamp": str(now_ms - 5000)}
        delay = BybitClient._parse_reset_delay_from_headers(headers)
        assert delay == 0.1

    def test_far_future_capped_at_10(self):
        now_ms = int(time.time() * 1000)
        headers = {"X-Bapi-Limit-Reset-Timestamp": str(now_ms + 60000)}
        delay = BybitClient._parse_reset_delay_from_headers(headers)
        assert delay == 10.0


# --- Public methods (integration with _request mock) ---


class TestTestConnection:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_success(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [{"totalEquity": "100"}]}
            result = await client.test_connection()
        assert result == {"success": True, "uid": None, "error": None}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_api_error(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = BybitAPIError(10003, "Invalid key")
            result = await client.test_connection()
        assert result["success"] is False
        assert "Invalid key" in result["error"]


class TestGetWalletBalance:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_with_data(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [{
                "totalEquity": "5000",
                "totalWalletBalance": "4000",
                "totalAvailableBalance": "3000",
                "totalPerpUPL": "100",
                "accountIMRate": "0.1",
                "accountMMRate": "0.05",
                "coin": [{"coin": "USDT"}],
            }]}
            result = await client.get_wallet_balance()
        assert result["totalEquity"] == "5000"
        assert result["coin"] == [{"coin": "USDT"}]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_list(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": []}
            result = await client.get_wallet_balance()
        assert result["totalEquity"] == "0"
        assert result["coin"] == []


class TestGetPositions:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_non_zero_positions(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {
                "list": [
                    {"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "avgPrice": "50000",
                     "markPrice": "51000", "unrealisedPnl": "100", "leverage": "10",
                     "liqPrice": "45000", "takeProfit": "55000", "stopLoss": "48000",
                     "positionIM": "500", "positionMM": "50", "positionIdx": "0"},
                    {"symbol": "ETHUSDT", "side": "Sell", "size": "0", "avgPrice": "0",
                     "markPrice": "0", "unrealisedPnl": "0", "leverage": "1",
                     "liqPrice": "0", "takeProfit": "", "stopLoss": "",
                     "positionIM": "0", "positionMM": "0", "positionIdx": "0"},
                ],
                "nextPageCursor": "",
            }
            result = await client.get_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_with_symbol_filter(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [], "nextPageCursor": ""}
            await client.get_positions(symbol="BTCUSDT")
            call_params = mock_req.call_args[0][2]
            assert call_params["symbol"] == "BTCUSDT"
            assert "settleCoin" not in call_params

    @pytest.mark.asyncio(loop_scope="function")
    async def test_pagination(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {"list": [{"symbol": "A", "size": "1", "side": "Buy", "avgPrice": "1",
                           "markPrice": "1", "unrealisedPnl": "0", "leverage": "1",
                           "liqPrice": "0", "takeProfit": "", "stopLoss": "",
                           "positionIM": "0", "positionMM": "0", "positionIdx": "0"}],
                 "nextPageCursor": "page2"},
                {"list": [{"symbol": "B", "size": "2", "side": "Sell", "avgPrice": "2",
                           "markPrice": "2", "unrealisedPnl": "0", "leverage": "1",
                           "liqPrice": "0", "takeProfit": "", "stopLoss": "",
                           "positionIM": "0", "positionMM": "0", "positionIdx": "0"}],
                 "nextPageCursor": ""},
            ]
            result = await client.get_positions()
        assert len(result) == 2
        assert mock_req.call_count == 2


class TestGetOpenOrders:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_orders(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [
                {"orderId": "o1", "symbol": "BTCUSDT", "side": "Buy",
                 "orderType": "Limit", "qty": "0.01", "price": "50000",
                 "orderStatus": "New", "createdTime": "123", "triggerPrice": "",
                 "stopOrderType": ""},
            ]}
            result = await client.get_open_orders()
        assert len(result) == 1
        assert result[0]["orderId"] == "o1"


class TestGetClosedPnl:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_pnl_with_cursor(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [{"closedPnl": "50"}], "nextPageCursor": "next"}
            result = await client.get_closed_pnl(1000, 2000, limit=50, cursor="abc")
        assert result["list"] == [{"closedPnl": "50"}]
        assert result["nextPageCursor"] == "next"
        call_params = mock_req.call_args[0][2]
        assert call_params["cursor"] == "abc"


class TestPlaceMarketCloseOrder:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_flips_side(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"orderId": "close1", "orderLinkId": "x"}
            result = await client.place_market_close_order("BTCUSDT", "Buy", "0.1")
        assert result["orderId"] == "close1"
        call_params = mock_req.call_args_list[0][0][2]
        assert call_params["side"] == "Sell"  # flipped
        assert call_params["reduceOnly"] is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_position_mode_retry(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                BybitAPIError(110043, "position idx not match"),
                {"orderId": "close2", "orderLinkId": "y"},
                {"list": [{"orderStatus": "Filled", "avgPrice": "100", "cumExecFee": "0.1", "cumExecQty": "0.1"}]},
            ]
            result = await client.place_market_close_order("BTCUSDT", "Buy", "0.1", position_idx=0)
        assert result["orderId"] == "close2"
        # Second call (index 1) uses hedge idx
        second_call_params = mock_req.call_args_list[1][0][2]
        assert second_call_params["positionIdx"] == 1  # Sell side for close of Buy

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_position_mode_error_raises(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = BybitAPIError(99999, "some other error")
            with pytest.raises(BybitAPIError):
                await client.place_market_close_order("BTCUSDT", "Sell", "1")


class TestSetLeverage:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_success(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await client.set_leverage("BTCUSDT", 10)
        assert result == {"status": "ok"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_already_at_target(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = BybitAPIError(110043, "leverage not modified")
            result = await client.set_leverage("BTCUSDT", 10)
        assert result == {"status": "unchanged"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_other_error_raises(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = BybitAPIError(10001, "bad request")
            with pytest.raises(BybitAPIError):
                await client.set_leverage("BTCUSDT", 10)


class TestPlaceMarketOrder:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_basic_order(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"orderId": "ord1", "orderLinkId": "link1"}
            result = await client.place_market_order("BTCUSDT", "Buy", "0.01")
        assert result["orderId"] == "ord1"
        call_params = mock_req.call_args_list[0][0][2]
        assert call_params["orderType"] == "Market"
        assert "takeProfit" not in call_params

    @pytest.mark.asyncio(loop_scope="function")
    async def test_with_tp_sl(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"orderId": "ord2", "orderLinkId": "link2"}
            await client.place_market_order("BTCUSDT", "Buy", "0.01", take_profit="60000", stop_loss="45000")
        call_params = mock_req.call_args_list[0][0][2]
        assert call_params["takeProfit"] == "60000"
        assert call_params["stopLoss"] == "45000"
        assert call_params["tpTriggerBy"] == "MarkPrice"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_position_mode_mismatch_retry(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                BybitAPIError(10001, "position idx not match"),
                {"orderId": "ord3", "orderLinkId": "link3"},
                {"list": [{"orderStatus": "Filled", "avgPrice": "100", "cumExecFee": "0.1", "cumExecQty": "0.01"}]},
            ]
            result = await client.place_market_order("BTCUSDT", "Buy", "0.01")
        assert result["orderId"] == "ord3"
        second_call_params = mock_req.call_args_list[1][0][2]
        assert second_call_params["positionIdx"] == 1  # Buy hedge idx

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_position_error_raises(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = BybitAPIError(10010, "insufficient balance")
            with pytest.raises(BybitAPIError):
                await client.place_market_order("BTCUSDT", "Sell", "1")


class TestGetMarkPrice:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_success(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [{"markPrice": "50123.45"}]}
            price = await client.get_mark_price("BTCUSDT")
        assert price == "50123.45"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_tickers(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": []}
            with pytest.raises(ValueError, match="No ticker data"):
                await client.get_mark_price("INVALID")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_zero_price(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [{"markPrice": "0"}]}
            with pytest.raises(ValueError, match="unavailable"):
                await client.get_mark_price("BTCUSDT")


class TestGetInstrumentInfo:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_success(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": [{"symbol": "BTCUSDT", "lotSizeFilter": {}}]}
            result = await client.get_instrument_info("BTCUSDT")
        assert result["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_found(self, client: BybitClient):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"list": []}
            with pytest.raises(ValueError, match="No instrument info"):
                await client.get_instrument_info("FAKE")


# --- Rate limit waiting ---


class TestWaitForRateLimit:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_under_limit_passes(self, client: BybitClient):
        # Should return immediately when under limit
        await client._wait_for_rate_limit()
        assert len(client._request_timestamps) == 1


# --- BybitAPIError ---


class TestBybitAPIError:
    def test_str_representation(self):
        e = BybitAPIError(10001, "bad request")
        assert "10001" in str(e)
        assert "bad request" in str(e)

    def test_attributes(self):
        e = BybitAPIError(500, "internal")
        assert e.ret_code == 500
        assert e.ret_msg == "internal"
