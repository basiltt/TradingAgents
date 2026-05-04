"""Tests for tradingagents.dataflows.interface — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import pytest


class TestGetCategoryForMethod:
    def test_known_method(self):
        from tradingagents.dataflows.interface import get_category_for_method
        assert get_category_for_method("get_stock_data") == "core_stock_apis"
        assert get_category_for_method("get_indicators") == "technical_indicators"
        assert get_category_for_method("get_fundamentals") == "fundamental_data"
        assert get_category_for_method("get_news") == "news_data"

    def test_unknown_method_raises(self):
        from tradingagents.dataflows.interface import get_category_for_method
        with pytest.raises(ValueError, match="not found"):
            get_category_for_method("nonexistent")


class TestGetVendor:
    @patch("tradingagents.dataflows.interface.get_config")
    def test_tool_level_overrides_category(self, mock_config):
        from tradingagents.dataflows.interface import get_vendor
        mock_config.return_value = {
            "data_vendors": {"core_stock_apis": "yfinance"},
            "tool_vendors": {"get_stock_data": "alpha_vantage"},
        }
        assert get_vendor("core_stock_apis", "get_stock_data") == "alpha_vantage"

    @patch("tradingagents.dataflows.interface.get_config")
    def test_category_fallback(self, mock_config):
        from tradingagents.dataflows.interface import get_vendor
        mock_config.return_value = {
            "data_vendors": {"core_stock_apis": "yfinance"},
            "tool_vendors": {},
        }
        assert get_vendor("core_stock_apis", "get_stock_data") == "yfinance"

    @patch("tradingagents.dataflows.interface.get_config")
    def test_default_when_not_configured(self, mock_config):
        from tradingagents.dataflows.interface import get_vendor
        mock_config.return_value = {"data_vendors": {}, "tool_vendors": {}}
        assert get_vendor("core_stock_apis") == "default"


class TestRouteToVendor:
    @patch("tradingagents.dataflows.interface.get_config")
    def test_routes_to_primary_vendor(self, mock_config):
        from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS
        mock_config.return_value = {
            "data_vendors": {"fundamental_data": "yfinance"},
            "tool_vendors": {},
        }
        mock_fn = MagicMock(return_value="result")
        original = VENDOR_METHODS["get_fundamentals"]["yfinance"]
        VENDOR_METHODS["get_fundamentals"]["yfinance"] = mock_fn
        try:
            result = route_to_vendor("get_fundamentals", "AAPL")
            assert result == "result"
        finally:
            VENDOR_METHODS["get_fundamentals"]["yfinance"] = original

    @patch("tradingagents.dataflows.interface.get_config")
    def test_fallback_on_rate_limit(self, mock_config):
        from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS
        from tradingagents.dataflows.alpha_vantage_common import AlphaVantageRateLimitError
        mock_config.return_value = {
            "data_vendors": {"fundamental_data": "alpha_vantage"},
            "tool_vendors": {},
        }
        orig_av = VENDOR_METHODS["get_fundamentals"]["alpha_vantage"]
        orig_yf = VENDOR_METHODS["get_fundamentals"]["yfinance"]
        VENDOR_METHODS["get_fundamentals"]["alpha_vantage"] = MagicMock(side_effect=AlphaVantageRateLimitError("x"))
        VENDOR_METHODS["get_fundamentals"]["yfinance"] = MagicMock(return_value="fallback_result")
        try:
            result = route_to_vendor("get_fundamentals", "AAPL")
            assert result == "fallback_result"
        finally:
            VENDOR_METHODS["get_fundamentals"]["alpha_vantage"] = orig_av
            VENDOR_METHODS["get_fundamentals"]["yfinance"] = orig_yf

    @patch("tradingagents.dataflows.interface.get_config")
    def test_all_vendors_rate_limited_raises(self, mock_config):
        from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS
        from tradingagents.dataflows.alpha_vantage_common import AlphaVantageRateLimitError
        mock_config.return_value = {
            "data_vendors": {"fundamental_data": "alpha_vantage"},
            "tool_vendors": {},
        }
        orig_av = VENDOR_METHODS["get_fundamentals"]["alpha_vantage"]
        orig_yf = VENDOR_METHODS["get_fundamentals"]["yfinance"]
        VENDOR_METHODS["get_fundamentals"]["alpha_vantage"] = MagicMock(side_effect=AlphaVantageRateLimitError("x"))
        VENDOR_METHODS["get_fundamentals"]["yfinance"] = MagicMock(side_effect=AlphaVantageRateLimitError("x"))
        try:
            with pytest.raises(RuntimeError, match="No available vendor"):
                route_to_vendor("get_fundamentals", "AAPL")
        finally:
            VENDOR_METHODS["get_fundamentals"]["alpha_vantage"] = orig_av
            VENDOR_METHODS["get_fundamentals"]["yfinance"] = orig_yf

    @patch("tradingagents.dataflows.interface.get_config")
    def test_unsupported_method_raises(self, mock_config):
        from tradingagents.dataflows.interface import route_to_vendor
        mock_config.return_value = {"data_vendors": {}, "tool_vendors": {}}
        with pytest.raises(ValueError):
            route_to_vendor("nonexistent_method")


class TestAlphaVantageFundamentals:
    @patch("tradingagents.dataflows.alpha_vantage_fundamentals._make_api_request")
    def test_get_fundamentals(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_fundamentals import get_fundamentals
        mock_api.return_value = '{"Symbol": "AAPL"}'
        result = get_fundamentals("AAPL")
        assert result == '{"Symbol": "AAPL"}'
        mock_api.assert_called_once_with("OVERVIEW", {"symbol": "AAPL"})

    @patch("tradingagents.dataflows.alpha_vantage_fundamentals._make_api_request")
    def test_filter_reports_by_date(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_fundamentals import get_balance_sheet
        mock_api.return_value = {
            "annualReports": [
                {"fiscalDateEnding": "2024-12-31"},
                {"fiscalDateEnding": "2025-12-31"},
            ],
            "quarterlyReports": [
                {"fiscalDateEnding": "2024-06-30"},
            ],
        }
        result = get_balance_sheet("AAPL", curr_date="2025-01-01")
        assert len(result["annualReports"]) == 1
        assert result["annualReports"][0]["fiscalDateEnding"] == "2024-12-31"

    @patch("tradingagents.dataflows.alpha_vantage_fundamentals._make_api_request")
    def test_filter_no_date_returns_as_is(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_fundamentals import get_cashflow
        mock_api.return_value = {"annualReports": [{"fiscalDateEnding": "2025-12-31"}]}
        result = get_cashflow("AAPL", curr_date=None)
        assert len(result["annualReports"]) == 1

    @patch("tradingagents.dataflows.alpha_vantage_fundamentals._make_api_request")
    def test_filter_non_dict_returns_as_is(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_fundamentals import get_income_statement
        mock_api.return_value = "some csv text"
        result = get_income_statement("AAPL", curr_date="2025-01-01")
        assert result == "some csv text"
