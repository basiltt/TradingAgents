"""Tests for instrument info cache — per-symbol qty_step, min_qty, tick_size, max_leverage."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_instrument_response():
    """Mock Bybit instruments-info response."""
    return {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "100"},
                    "priceFilter": {"tickSize": "0.10"},
                    "leverageFilter": {"maxLeverage": "100"},
                },
                {
                    "symbol": "ETHUSDT",
                    "lotSizeFilter": {"qtyStep": "0.01", "minOrderQty": "0.01", "maxOrderQty": "1000"},
                    "priceFilter": {"tickSize": "0.01"},
                    "leverageFilter": {"maxLeverage": "75"},
                },
            ],
            "nextPageCursor": "",
        }
    }


class TestInstrumentCache:
    """Test InstrumentInfoCache."""

    @pytest.mark.asyncio
    async def test_fetches_and_caches_instrument_info(self):
        from backend.services.kline_cache_service import InstrumentInfoCache

        cache = InstrumentInfoCache()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _make_instrument_response()

        async def mock_get(*a, **kw):
            return resp

        class MockClient:
            get = staticmethod(mock_get)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=MockClient())
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.kline_cache_service.httpx.AsyncClient", return_value=cm):
            await cache.refresh()

        info = cache.get("BTCUSDT")
        assert info is not None
        assert info["qty_step"] == 0.001
        assert info["min_qty"] == 0.001
        assert info["tick_size"] == 0.10
        assert info["max_leverage"] == 100

        info_eth = cache.get("ETHUSDT")
        assert info_eth["qty_step"] == 0.01
        assert info_eth["max_leverage"] == 75

    def test_returns_none_for_unknown_symbol(self):
        from backend.services.kline_cache_service import InstrumentInfoCache

        cache = InstrumentInfoCache()
        assert cache.get("UNKNOWNUSDT") is None

    def test_returns_defaults_via_get_or_default(self):
        from backend.services.kline_cache_service import InstrumentInfoCache

        cache = InstrumentInfoCache()
        info = cache.get_or_default("UNKNOWNUSDT")
        assert info["qty_step"] == 0.001
        assert info["min_qty"] == 0.001
        assert info["tick_size"] == 0.01
        assert info["max_leverage"] == 25  # conservative default
