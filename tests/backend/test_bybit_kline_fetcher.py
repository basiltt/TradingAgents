"""Tests for Bybit kline async fetcher — paginated, rate-limited, with retry."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_response_page():
    """Single page of Bybit kline response (descending, string arrays)."""
    return {
        "retCode": 0,
        "result": {
            "list": [
                ["1704110400000", "50200.0", "50300.0", "50100.0", "50250.0", "120.5", "6055000"],
                ["1704110100000", "50100.0", "50200.0", "50000.0", "50200.0", "95.3", "4780000"],
                ["1704109800000", "50000.0", "50150.0", "49950.0", "50100.0", "110.0", "5510000"],
            ]
        }
    }


def _make_mock_resp(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    resp.text = "error"
    return resp


def _make_mock_client(responses):
    """Create a mock httpx client with real async function for .get()."""
    if not isinstance(responses, list):
        responses = [responses]
    call_idx = {"i": 0}

    async def mock_get(*args, **kwargs):
        idx = call_idx["i"]
        call_idx["i"] += 1
        if idx < len(responses):
            return responses[idx]
        return responses[-1]

    class MockClient:
        pass

    client = MockClient()
    client.get = mock_get
    client._call_count = call_idx

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, client


class TestBybitKlineFetcher:
    """Test the internal _fetch_klines_from_bybit method."""

    @pytest.mark.asyncio
    async def test_parses_response_to_ascending_dicts(self, mock_response_page):
        from backend.services.kline_cache_service import KlineCacheService

        mock_db = MagicMock()
        mock_db.pool = AsyncMock()
        svc = KlineCacheService(db=mock_db)

        ok_resp = _make_mock_resp(200, mock_response_page)
        cm, client = _make_mock_client(ok_resp)

        with patch("backend.services.kline_cache_service.httpx.AsyncClient", return_value=cm):
            # start_ms = oldest candle ts → pagination stops after 1 page
            start = datetime.fromtimestamp(1704109800, tz=timezone.utc)
            end = datetime.fromtimestamp(1704110500, tz=timezone.utc)
            klines = await svc._fetch_klines_from_bybit("BTCUSDT", "5m", start, end)

        assert len(klines) == 3
        assert klines[0]["open_time"] < klines[1]["open_time"] < klines[2]["open_time"]
        assert isinstance(klines[0]["open"], float)
        assert klines[0]["open"] == 50000.0

    @pytest.mark.asyncio
    async def test_one_minute_interval_maps_to_bybit_1(self, mock_response_page):
        """1m drill-down requires the cache to fetch the Bybit "1" interval code.
        The interval_map historically lacked "1m" (5m/15m/1h/4h/1d only), so a 1m
        request would pass "1m" through verbatim and Bybit would reject it."""
        from backend.services.kline_cache_service import KlineCacheService

        mock_db = MagicMock()
        mock_db.pool = AsyncMock()
        svc = KlineCacheService(db=mock_db)

        captured = {}
        ok_resp = _make_mock_resp(200, mock_response_page)

        async def capturing_get(*args, **kwargs):
            captured["params"] = kwargs.get("params")
            return ok_resp

        client = MagicMock()
        client.get = capturing_get
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.kline_cache_service.httpx.AsyncClient", return_value=cm):
            start = datetime.fromtimestamp(1704109800, tz=timezone.utc)
            end = datetime.fromtimestamp(1704110500, tz=timezone.utc)
            await svc._fetch_klines_from_bybit("BTCUSDT", "1m", start, end)

        assert captured["params"]["interval"] == "1", (
            f"expected Bybit interval '1' for '1m', got {captured['params']['interval']!r}"
        )

    @pytest.mark.asyncio
    async def test_handles_empty_response(self):
        from backend.services.kline_cache_service import KlineCacheService

        mock_db = MagicMock()
        mock_db.pool = AsyncMock()
        svc = KlineCacheService(db=mock_db)

        empty_resp = _make_mock_resp(200, {"retCode": 0, "result": {"list": []}})
        cm, client = _make_mock_client(empty_resp)

        with patch("backend.services.kline_cache_service.httpx.AsyncClient", return_value=cm):
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
            klines = await svc._fetch_klines_from_bybit("XYZUSDT", "5m", start, end)

        assert klines == []

    @pytest.mark.asyncio
    async def test_retries_on_server_error(self):
        from backend.services.kline_cache_service import KlineCacheService

        mock_db = MagicMock()
        mock_db.pool = AsyncMock()
        svc = KlineCacheService(db=mock_db)

        fail_resp = _make_mock_resp(500)
        ok_resp = _make_mock_resp(200, {"retCode": 0, "result": {"list": [
            ["1704110400000", "50000.0", "50100.0", "49900.0", "50050.0", "100.0", "5000000"],
        ]}})
        cm, client = _make_mock_client([fail_resp, ok_resp])

        with patch("backend.services.kline_cache_service.httpx.AsyncClient", return_value=cm):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # start_ms = oldest_ts → pagination stops after page 1
                start = datetime.fromtimestamp(1704110400, tz=timezone.utc)
                end = datetime.fromtimestamp(1704110500, tz=timezone.utc)
                klines = await svc._fetch_klines_from_bybit("BTCUSDT", "5m", start, end)

        assert len(klines) == 1
        assert client._call_count["i"] == 2  # 1 fail + 1 success
