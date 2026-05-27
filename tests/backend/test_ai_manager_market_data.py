"""Tests for MarketDataCache MTF extensions."""
import pytest
from backend.services.ai_manager_market_data import MarketDataCache


class TestMTFKlines:
    def test_get_mtf_klines_returns_all_timeframes(self):
        cache = MarketDataCache()
        cache._mtf_klines = {
            "BTCUSDT": {
                "5m": [[1, 100, 101, 99, 100.5, 50]],
                "15m": [[1, 100, 102, 98, 101, 100]],
                "1h": [[1, 100, 105, 95, 103, 500]],
                "4h": [[1, 100, 110, 90, 108, 2000]],
            }
        }
        result = cache.get_mtf_klines("BTCUSDT")
        assert "15m" in result
        assert "1h" in result
        assert "4h" in result

    def test_get_mtf_klines_unknown_symbol(self):
        cache = MarketDataCache()
        cache._mtf_klines = {}
        result = cache.get_mtf_klines("UNKNOWN")
        assert result == {}

    def test_get_klines_by_timeframe(self):
        cache = MarketDataCache()
        cache._mtf_klines = {"BTCUSDT": {"1h": [[1, 2, 3, 4, 5, 6]]}}
        result = cache.get_klines("BTCUSDT", "1h")
        assert result == [[1, 2, 3, 4, 5, 6]]

    def test_get_klines_5m_uses_kline_data(self):
        cache = MarketDataCache()
        cache._kline_data = {"BTCUSDT": [[1, 100, 101, 99, 100.5, 50]]}
        result = cache.get_klines("BTCUSDT", "5m")
        assert result == [[1, 100, 101, 99, 100.5, 50]]

    def test_get_klines_missing_timeframe_returns_none(self):
        cache = MarketDataCache()
        cache._mtf_klines = {}
        result = cache.get_klines("BTCUSDT", "4h")
        assert result is None

    def test_mtf_tasks_initialized_empty(self):
        cache = MarketDataCache()
        assert cache._mtf_tasks == []

    def test_mtf_klines_initialized_empty(self):
        cache = MarketDataCache()
        assert cache._mtf_klines == {}
