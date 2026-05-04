"""Tests for tradingagents.dataflows.coingecko_data — Phase 1 unit tests."""

import threading
import time
from unittest.mock import patch, MagicMock

import pytest


class TestGetCoinId:
    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_strips_usdt_suffix(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        mock_fetch.return_value = {"BTC": "bitcoin", "ETH": "ethereum"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCUSDT")
        assert result == "bitcoin"

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_strips_usd_suffix(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        mock_fetch.return_value = {"BTC": "bitcoin"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCUSD")
        assert result == "bitcoin"

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_strips_perp_suffix(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        mock_fetch.return_value = {"BTC": "bitcoin"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCPERP")
        assert result == "bitcoin"

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list")
    def test_unknown_symbol_returns_none(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        mock_fetch.return_value = {"BTC": "bitcoin"}
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("XYZUSDT")
        assert result is None

    @patch("tradingagents.dataflows.coingecko_data._fetch_coin_list", side_effect=Exception("network"))
    def test_fetch_failure_returns_none_when_cache_empty(self, mock_fetch):
        from tradingagents.dataflows.coingecko_data import _get_coin_id, _coin_list_cache, _coin_list_lock
        with _coin_list_lock:
            _coin_list_cache.clear()
        result = _get_coin_id("BTCUSDT")
        assert result is None

    def test_fetch_failure_clears_cache_and_returns_none(self):
        import tradingagents.dataflows.coingecko_data as mod
        with mod._coin_list_lock:
            mod._coin_list_cache.clear()
            mod._coin_list_cache["BTC"] = "bitcoin"
            mod._coin_list_ts = 0  # force refresh attempt
        with patch.object(mod, "_fetch_coin_list", side_effect=Exception("network")):
            result = mod._get_coin_id("BTCUSDT")
        # Cache is cleared before fetch, so on failure it's empty → None
        assert result is None


class TestFetchCoinList:
    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_builds_mapping(self, mock_session):
        from tradingagents.dataflows.coingecko_data import _fetch_coin_list
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

    @patch("tradingagents.dataflows.coingecko_data.time.sleep")
    def test_sleeps_when_at_limit(self, mock_sleep):
        from tradingagents.dataflows.coingecko_data import _RateLimiter
        limiter = _RateLimiter(max_per_min=2)
        now = time.time()
        limiter._timestamps = [now - 10, now - 5]
        limiter.wait()
        mock_sleep.assert_called_once()


class TestConfigureCoingeckoConcurrency:
    def test_sets_semaphore(self):
        from tradingagents.dataflows.coingecko_data import configure_coingecko_concurrency, _coingecko_semaphore
        configure_coingecko_concurrency(5)
        import tradingagents.dataflows.coingecko_data as mod
        assert isinstance(mod._coingecko_semaphore, threading.Semaphore)


class TestCachedGet:
    @patch("tradingagents.dataflows.coingecko_data._limiter")
    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_returns_json(self, mock_session, mock_limiter):
        from tradingagents.dataflows.coingecko_data import _cached_get, _cache, _cache_lock
        with _cache_lock:
            _cache.clear()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key": "value"}
        mock_session.get.return_value = mock_resp
        result = _cached_get("http://test.com/api")
        assert result == {"key": "value"}

    @patch("tradingagents.dataflows.coingecko_data._limiter")
    @patch("tradingagents.dataflows.coingecko_data._SESSION")
    def test_cache_hit(self, mock_session, mock_limiter):
        import json as _json
        from tradingagents.dataflows.coingecko_data import _cached_get, _cache, _cache_lock
        with _cache_lock:
            _cache["http://cached.com/api"] = (time.time(), _json.dumps({"cached": True}))
        result = _cached_get("http://cached.com/api")
        assert result == {"cached": True}
        mock_session.get.assert_not_called()


class TestGetCoingeckoMarketData:
    @patch("tradingagents.dataflows.coingecko_data._cached_get")
    @patch("tradingagents.dataflows.coingecko_data._get_coin_id", return_value="bitcoin")
    def test_happy_path(self, mock_id, mock_get):
        from tradingagents.dataflows.coingecko_data import get_coingecko_market_data
        mock_get.return_value = {
            "name": "Bitcoin",
            "symbol": "btc",
            "market_cap_rank": 1,
            "market_data": {
                "market_cap": {"usd": 1000000000},
                "total_volume": {"usd": 50000000},
                "current_price": {"usd": 50000},
                "circulating_supply": 19000000,
                "total_supply": 21000000,
                "max_supply": 21000000,
                "ath": {"usd": 69000},
                "ath_change_percentage": {"usd": -27.5},
                "atl": {"usd": 67.81},
                "fully_diluted_valuation": {"usd": 1050000000},
                "price_change_percentage_24h": 2.5,
                "price_change_percentage_7d": -1.3,
            },
            "description": {"en": "Bitcoin is a decentralized digital currency."},
            "categories": ["Cryptocurrency", "Layer 1"],
        }
        result = get_coingecko_market_data("BTCUSDT")
        assert "Bitcoin" in result
        assert "Market Cap Rank" in result
        assert "Categories" in result

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
            "name": "Bitcoin",
            "symbol": "btc",
            "community_data": {
                "twitter_followers": 5000000,
                "reddit_subscribers": 4000000,
                "reddit_accounts_active_48h": 50000,
                "telegram_channel_user_count": 100000,
            },
            "developer_data": {
                "forks": 35000,
                "stars": 70000,
                "subscribers": 4000,
                "total_issues": 7000,
                "closed_issues": 6500,
                "pull_requests_merged": 200,
                "pull_request_contributors": 50,
                "commit_count_4_weeks": 100,
                "code_additions_deletions_4_weeks": {"additions": 5000, "deletions": 3000},
            },
            "sentiment_votes_up_percentage": 75.0,
            "sentiment_votes_down_percentage": 25.0,
            "links": {
                "homepage": ["https://bitcoin.org"],
                "repos_url": {"github": ["https://github.com/bitcoin/bitcoin"]},
            },
        }
        result = get_coingecko_community_data("BTCUSDT")
        assert "Community" in result
        assert "Twitter" in result
        assert "Developer Activity" in result
        assert "bitcoin.org" in result
        assert "github.com" in result

    @patch("tradingagents.dataflows.coingecko_data._get_coin_id", return_value=None)
    def test_unresolved_symbol(self, mock_id):
        from tradingagents.dataflows.coingecko_data import get_coingecko_community_data
        result = get_coingecko_community_data("UNKNOWN")
        assert "Could not resolve" in result
