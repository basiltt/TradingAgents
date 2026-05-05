"""Tests for tradingagents.dataflows.alpha_vantage_news and alpha_vantage_stock — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import pytest


class TestGetNews:
    @patch("tradingagents.dataflows.alpha_vantage_news._make_api_request")
    @patch("tradingagents.dataflows.alpha_vantage_news.format_datetime_for_api")
    def test_happy_path(self, mock_fmt, mock_api):
        from tradingagents.dataflows.alpha_vantage_news import get_news
        mock_fmt.side_effect = lambda x: f"formatted_{x}"
        mock_api.return_value = {"feed": [{"title": "News1"}]}
        result = get_news("AAPL", "2025-01-01", "2025-01-10")
        assert result == {"feed": [{"title": "News1"}]}
        mock_api.assert_called_once_with("NEWS_SENTIMENT", {
            "tickers": "AAPL",
            "time_from": "formatted_2025-01-01",
            "time_to": "formatted_2025-01-10",
        })


class TestGetGlobalNews:
    @patch("tradingagents.dataflows.alpha_vantage_news._make_api_request")
    @patch("tradingagents.dataflows.alpha_vantage_news.format_datetime_for_api")
    def test_happy_path(self, mock_fmt, mock_api):
        from tradingagents.dataflows.alpha_vantage_news import get_global_news
        mock_fmt.side_effect = lambda x: f"formatted_{x}"
        mock_api.return_value = {"feed": []}
        result = get_global_news("2025-01-10", look_back_days=7, limit=50)
        assert result == {"feed": []}
        call_params = mock_api.call_args[0][1]
        assert call_params["limit"] == "50"
        assert "financial_markets" in call_params["topics"]


class TestGetInsiderTransactionsAV:
    @patch("tradingagents.dataflows.alpha_vantage_news._make_api_request")
    def test_happy_path(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_news import get_insider_transactions
        mock_api.return_value = {"data": []}
        result = get_insider_transactions("IBM")
        mock_api.assert_called_once_with("INSIDER_TRANSACTIONS", {"symbol": "IBM"})


class TestGetStock:
    @patch("tradingagents.dataflows.alpha_vantage_stock._make_api_request")
    @patch("tradingagents.dataflows.alpha_vantage_stock._filter_csv_by_date_range")
    def test_compact_for_recent_dates(self, mock_filter, mock_api):
        from tradingagents.dataflows.alpha_vantage_stock import get_stock
        mock_api.return_value = "csv data"
        mock_filter.return_value = "filtered csv"
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        result = get_stock("AAPL", today, today)
        call_params = mock_api.call_args[0][1]
        assert call_params["outputsize"] == "compact"
        assert result == "filtered csv"

    @patch("tradingagents.dataflows.alpha_vantage_stock._make_api_request")
    @patch("tradingagents.dataflows.alpha_vantage_stock._filter_csv_by_date_range")
    def test_full_for_old_dates(self, mock_filter, mock_api):
        from tradingagents.dataflows.alpha_vantage_stock import get_stock
        mock_api.return_value = "csv data"
        mock_filter.return_value = "filtered csv"
        result = get_stock("AAPL", "2020-01-01", "2020-06-01")
        call_params = mock_api.call_args[0][1]
        assert call_params["outputsize"] == "full"
