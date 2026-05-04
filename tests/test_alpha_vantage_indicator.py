"""Tests for tradingagents.dataflows.alpha_vantage_indicator — Phase 1 unit tests."""

from unittest.mock import patch
import pytest


class TestGetIndicator:
    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_unsupported_indicator_raises(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        with pytest.raises(ValueError, match="not supported"):
            get_indicator("AAPL", "bogus_indicator", "2025-01-10", 5)

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_sma_50(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,SMA\n2025-01-08,150.0\n2025-01-09,151.0\n2025-01-10,152.0\n"
        result = get_indicator("AAPL", "close_50_sma", "2025-01-10", 5)
        assert "152.0" in result
        assert "SMA" in result.upper()

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_sma_200(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,SMA\n2025-01-10,200.0\n"
        result = get_indicator("AAPL", "close_200_sma", "2025-01-10", 5)
        assert "200.0" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_ema(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,EMA\n2025-01-10,155.0\n"
        result = get_indicator("AAPL", "close_10_ema", "2025-01-10", 5)
        assert "155.0" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_rsi(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,RSI\n2025-01-10,65.3\n"
        result = get_indicator("AAPL", "rsi", "2025-01-10", 5)
        assert "65.3" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_macd(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,MACD,MACD_Signal,MACD_Hist\n2025-01-10,1.5,1.2,0.3\n"
        result = get_indicator("AAPL", "macd", "2025-01-10", 5)
        assert "1.5" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_macds(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,MACD,MACD_Signal,MACD_Hist\n2025-01-10,1.5,1.2,0.3\n"
        result = get_indicator("AAPL", "macds", "2025-01-10", 5)
        assert "1.2" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_bbands(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,Real Upper Band,Real Middle Band,Real Lower Band\n2025-01-10,160,155,150\n"
        result = get_indicator("AAPL", "boll", "2025-01-10", 5)
        assert "155" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_atr(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,ATR\n2025-01-10,3.5\n"
        result = get_indicator("AAPL", "atr", "2025-01-10", 5)
        assert "3.5" in result

    def test_vwma_returns_info_message(self):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        result = get_indicator("AAPL", "vwma", "2025-01-10", 5)
        assert "VWMA" in result
        assert "not directly available" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_no_data_returned(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,SMA\n"  # header only
        result = get_indicator("AAPL", "close_50_sma", "2025-01-10", 5)
        assert "No data" in result or "Error" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_missing_time_column(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "date,SMA\n2025-01-10,50.0\n"
        result = get_indicator("AAPL", "close_50_sma", "2025-01-10", 5)
        assert "'time' column not found" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_missing_target_column(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,OTHER\n2025-01-10,50.0\n"
        result = get_indicator("AAPL", "close_50_sma", "2025-01-10", 5)
        assert "not found" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request")
    def test_dates_outside_range_return_no_data(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        mock_api.return_value = "time,SMA\n2024-01-10,50.0\n"
        result = get_indicator("AAPL", "close_50_sma", "2025-01-10", 5)
        assert "No data available" in result

    @patch("tradingagents.dataflows.alpha_vantage_indicator._make_api_request", side_effect=RuntimeError("fail"))
    def test_exception_returns_error(self, mock_api):
        from tradingagents.dataflows.alpha_vantage_indicator import get_indicator
        result = get_indicator("AAPL", "rsi", "2025-01-10", 5)
        assert "Error retrieving" in result
