"""Tests for tradingagents.dataflows.coingecko_data."""

import os
import threading
import time
from unittest.mock import patch, MagicMock

import pytest


def _force_configured():
    """Set module as configured so tests don't trigger real _configure()."""
    import tradingagents.dataflows.coingecko_data as mod
    mod._configured = True
    mod._BASE = "https://api.coingecko.com/api/v3"
    mod._API_KEY = ""
    mod._AUTH_MODE = None
    mod._plan = "demo"
    mod._limiter = mod._RateLimiter(max_per_min=30)
    mod._coingecko_semaphore = threading.Semaphore(2)


class TestGetCoinId:
    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_strips_usdt_suffix(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        _force_configured()
        mock_fetch.return_value = {"BTC": "bitcoin", "ETH": "ethereum"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCUSDT")
        assert result == "bitcoin"

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_strips_usd_suffix(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        _force_configured()
        mock_fetch.return_value = {"BTC": "bitcoin"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCUSD")
        assert result == "bitcoin"

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_strips_perp_suffix(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        _force_configured()
        mock_fetch.return_value = {"BTC": "bitcoin"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCPERP")
        assert result == "bitcoin"

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_unknown_symbol_returns_none(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        _force_configured()
        mock_fetch.return_value = {"BTC": "bitcoin"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("XYZUSDT")
        assert result is None

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list", side_effect=Exception("network"))
    def test_fetch_failure_returns_none_when_cache_empty(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        _force_configured()
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCUSDT")
        assert result is None

    def test_fetch_failure_preserves_existing_cache(self):
        import tradingagents.dataflows.coingecko_data as mod
        _force_configured()
        with mod._coin_list_lock:
            mod._coin_list_cache.clear()
            mod._coin_list_cache["BTC"] = "bitcoin"
            mod._coin_list_ts = 0
        with patch.object(mod, "_fetch_coin_list", side_effect=Exception("network")):
            result = mod._get_coin_id("BTCUSDT")
        assert result == "bitcoin"


class TestFetchCoinList:
    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_builds_mapping(self, mock_session):
        from tradingagents.dataflows.coingecko_data import _fetch_coin_list
        _force_configured()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"symbol": "btc", "id": "bitcoin"},
            {"symbol": "eth", "id": "ethereum"},
            {"symbol": "", "id": "empty"},
        ]
        mock_session.get.return_value = mock_resp
        result = _fetch_coin_list()
        assert result == {"BTC": "bitcoin", "ETH": "ethereum"}

    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_first_symbol_wins(self, mock_session):
        from tradingagents.dataflows.coingecko_data import _fetch_coin_list
        _force_configured()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"symbol": "btc", "id": "bitcoin"},
            {"symbol": "btc", "id": "bitcoin-wrapped"},
        ]
        mock_session.get.return_value = mock_resp
        result = _fetch_coin_list()
        assert result["BTC"] == "bitcoin"


class TestRateLimiter:
    def test_no_sleep_under_limit(self):
        from tradingagents.dataflows.coingecko_data import _RateLimiter
        limiter = _RateLimiter(max_per_min=5)
        limiter.wait()
        assert len(limiter._timestamps) == 1

    def test_rpm_property(self):
        from tradingagents.dataflows.coingecko_data import _RateLimiter
        limiter = _RateLimiter(max_per_min=250)
        assert limiter.rpm == 250

    @patch("tradingagents.dataflows.coingecko_data.time.sleep")
    def test_sleeps_when_at_limit(self, mock_sleep):
        from tradingagents.dataflows.coingecko_data import _RateLimiter
        limiter = _RateLimiter(max_per_min=2)
        now = time.time()
        limiter._timestamps = [now, now]
        mock_sleep.side_effect = lambda _: limiter._timestamps.clear()
        limiter.wait()
        mock_sleep.assert_called_once()

    @patch("tradingagents.dataflows.coingecko_data.time.sleep")
    def test_sleep_not_capped_at_10s(self, mock_sleep):
        from tradingagents.dataflows.coingecko_data import _RateLimiter
        limiter = _RateLimiter(max_per_min=1)
        old_ts = time.time() - 5
        limiter._timestamps = [old_ts]
        mock_sleep.side_effect = lambda _: limiter._timestamps.clear()
        limiter.wait()
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg > 10.0


class TestTierConfiguration:
    def test_no_key_defaults_to_demo(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "", "COINGECKO_PLAN": ""}, clear=False):
            mod._configure()
        assert mod._plan == "demo"
        assert mod._AUTH_MODE is None
        assert mod._BASE == "https://api.coingecko.com/api/v3"

    def test_key_with_no_plan_defaults_to_demo(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "test-key", "COINGECKO_PLAN": ""}, clear=False):
            mod._configure()
        assert mod._plan == "demo"
        assert mod._AUTH_MODE == "header"

    def test_basic_plan_with_key(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "test-key", "COINGECKO_PLAN": "basic"}, clear=False):
            mod._configure()
        assert mod._plan == "basic"
        assert mod._BASE == "https://pro-api.coingecko.com/api/v3"
        assert mod._AUTH_MODE == "param"

    def test_basic_plan_without_key_falls_back_to_demo(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "", "COINGECKO_PLAN": "basic"}, clear=False):
            mod._configure()
        assert mod._plan == "demo"

    def test_invalid_plan_raises(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "", "COINGECKO_PLAN": "enterprise"}, clear=False):
            with pytest.raises(ValueError, match="Invalid COINGECKO_PLAN"):
                mod._configure()

    def test_rpm_override(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "", "COINGECKO_PLAN": "", "COINGECKO_RATE_LIMIT_RPM": "100"}, clear=False):
            mod._configure()
        assert mod._limiter.rpm == 100

    def test_legacy_rpm_override(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        env = {"COINGECKO_API_KEY": "", "COINGECKO_PLAN": "", "COINGECKO_MAX_PER_MIN": "50"}
        with patch.dict("os.environ", env, clear=False):
            if "COINGECKO_RATE_LIMIT_RPM" in os.environ:
                del os.environ["COINGECKO_RATE_LIMIT_RPM"]
            mod._configure()
        assert mod._limiter.rpm == 50

    def test_concurrency_override(self):
        import tradingagents.dataflows.coingecko_data as mod
        mod._configured = False
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "", "COINGECKO_PLAN": "", "COINGECKO_MAX_CONCURRENT": "10"}, clear=False):
            mod._configure()


class TestCachedGet:
    @patch("tradingagents.dataflows.coingecko_data._limiter")
    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_returns_json(self, mock_session, mock_limiter):
        from tradingagents.dataflows.coingecko_data import _cached_get, _cache, _cache_lock
        _force_configured()
        with _cache_lock:
            _cache.clear()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key": "value"}
        mock_session.get.return_value = mock_resp
        result = _cached_get("/test/api")
        assert result == {"key": "value"}

    @patch("tradingagents.dataflows.coingecko_data._limiter")
    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_cache_hit(self, mock_session, mock_limiter):
        import json as _json
        from tradingagents.dataflows.coingecko_data import _cached_get, _cache, _cache_lock
        _force_configured()
        with _cache_lock:
            _cache["/cached/api"] = (time.time(), _json.dumps({"cached": True}))
        result = _cached_get("/cached/api")
        assert result == {"cached": True}
        mock_session.get.assert_not_called()


class TestBulkNormalization:
    def test_normalizes_flat_to_nested(self):
        from tradingagents.dataflows.coingecko_data import _normalize_bulk_to_coin_format
        bulk = {
            "name": "Bitcoin", "symbol": "btc", "market_cap_rank": 1,
            "market_cap": 1000000, "total_volume": 50000,
            "current_price": 50000, "circulating_supply": 19000000,
            "total_supply": 21000000, "max_supply": 21000000,
            "ath": 69000, "ath_change_percentage": -27.5,
            "atl": 67.81, "atl_change_percentage": 100000,
            "fully_diluted_valuation": 1050000000,
        }
        result = _normalize_bulk_to_coin_format(bulk)
        assert result["market_data"]["market_cap"]["usd"] == 1000000
        assert result["market_data"]["ath"]["usd"] == 69000
        assert result["name"] == "Bitcoin"

    def test_null_coalesced_to_zero(self):
        from tradingagents.dataflows.coingecko_data import _normalize_bulk_to_coin_format
        bulk = {
            "name": "Test", "symbol": "tst", "market_cap_rank": None,
            "market_cap": None, "total_volume": None,
            "current_price": None, "circulating_supply": None,
            "total_supply": None, "max_supply": None,
            "ath": None, "ath_change_percentage": None,
            "atl": None, "atl_change_percentage": None,
            "fully_diluted_valuation": None,
        }
        result = _normalize_bulk_to_coin_format(bulk)
        assert result["market_data"]["market_cap"]["usd"] == 0
        assert result["market_data"]["circulating_supply"] == 0
        assert result["market_data"]["max_supply"] is None


class TestGetCoingeckoMarketData:
    @patch("tradingagents.dataflows.coingecko_data._cached_get")
    @patch("tradingagents.dataflows.coingecko_data._get_coin_id", return_value="bitcoin")
    def test_happy_path(self, mock_id, mock_get):
        from tradingagents.dataflows.coingecko_data import get_coingecko_market_data
        mock_get.return_value = {
            "name": "Bitcoin", "symbol": "btc", "market_cap_rank": 1,
            "market_data": {
                "market_cap": {"usd": 1000000000},
                "total_volume": {"usd": 50000000},
                "current_price": {"usd": 50000},
                "circulating_supply": 19000000, "total_supply": 21000000,
                "max_supply": 21000000, "ath": {"usd": 69000},
                "ath_change_percentage": {"usd": -27.5}, "atl": {"usd": 67.81},
                "fully_diluted_valuation": {"usd": 1050000000},
                "price_change_percentage_24h": 2.5, "price_change_percentage_7d": -1.3,
            },
            "description": {"en": "Bitcoin is a decentralized digital currency."},
            "categories": ["Cryptocurrency", "Layer 1"],
        }
        result = get_coingecko_market_data("BTCUSDT")
        assert "Bitcoin" in result
        assert "Market Cap Rank" in result

    @patch("tradingagents.dataflows.coingecko_data._get_coin_id", return_value=None)
    def test_unresolved_symbol(self, mock_id):
        from tradingagents.dataflows.coingecko_data import get_coingecko_market_data
        result = get_coingecko_market_data("UNKNOWN")
        assert "Could not resolve" in result


class TestGetCoingeckoCommunityData:
    @patch("tradingagents.dataflows.coingecko_data._cached_get")
    @patch("tradingagents.dataflows.coingecko_data._get_coin_id", return_value="bitcoin")
    def test_happy_path(self, mock_id, mock_get):
        from tradingagents.dataflows.coingecko_data import get_coingecko_community_data
        mock_get.return_value = {
            "name": "Bitcoin", "symbol": "btc",
            "community_data": {"twitter_followers": 5000000, "reddit_subscribers": 4000000,
                               "reddit_accounts_active_48h": 50000, "telegram_channel_user_count": 100000},
            "developer_data": {"forks": 35000, "stars": 70000, "subscribers": 4000,
                               "total_issues": 7000, "closed_issues": 6500,
                               "pull_requests_merged": 200, "pull_request_contributors": 50,
                               "commit_count_4_weeks": 100,
                               "code_additions_deletions_4_weeks": {"additions": 5000, "deletions": 3000}},
            "sentiment_votes_up_percentage": 75.0, "sentiment_votes_down_percentage": 25.0,
            "links": {"homepage": ["https://bitcoin.org"],
                      "repos_url": {"github": ["https://github.com/bitcoin/bitcoin"]}},
        }
        result = get_coingecko_community_data("BTCUSDT")
        assert "Community" in result
        assert "Developer Activity" in result

    @patch("tradingagents.dataflows.coingecko_data._get_coin_id", return_value=None)
    def test_unresolved_symbol(self, mock_id):
        from tradingagents.dataflows.coingecko_data import get_coingecko_community_data
        result = get_coingecko_community_data("UNKNOWN")
        assert "Could not resolve" in result


class TestGetCoingeckoStatus:
    def test_returns_status_dict(self):
        import tradingagents.dataflows.coingecko_data as mod
        _force_configured()
        status = mod.get_coingecko_status()
        assert status["plan"] == "demo"
        assert status["key_configured"] is False
        assert isinstance(status["rate_limit_rpm"], int)
