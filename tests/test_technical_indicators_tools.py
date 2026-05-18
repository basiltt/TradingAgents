"""Tests for tradingagents.agents.utils.technical_indicators_tools."""

from unittest.mock import patch

PATCH = "tradingagents.agents.utils.technical_indicators_tools.route_to_vendor"


class TestGetIndicators:
    @patch(PATCH)
    def test_single_indicator(self, mock_route):
        from tradingagents.agents.utils.technical_indicators_tools import get_indicators
        mock_route.return_value = "RSI data"
        result = get_indicators.invoke({"symbol": "AAPL", "indicator": "rsi", "curr_date": "2025-01-15"})
        assert "RSI data" in result
        mock_route.assert_called_once_with("get_indicators", "AAPL", "rsi", "2025-01-15", 30)

    @patch(PATCH)
    def test_multiple_comma_separated(self, mock_route):
        from tradingagents.agents.utils.technical_indicators_tools import get_indicators
        mock_route.return_value = "data"
        get_indicators.invoke({"symbol": "AAPL", "indicator": "rsi, macd, ema", "curr_date": "2025-01-15"})
        assert mock_route.call_count == 3

    @patch(PATCH)
    def test_value_error_caught(self, mock_route):
        from tradingagents.agents.utils.technical_indicators_tools import get_indicators
        mock_route.side_effect = ValueError("Unknown indicator")
        result = get_indicators.invoke({"symbol": "AAPL", "indicator": "bad", "curr_date": "2025-01-15"})
        assert "Unknown indicator" in result

    @patch(PATCH)
    def test_custom_lookback(self, mock_route):
        from tradingagents.agents.utils.technical_indicators_tools import get_indicators
        mock_route.return_value = "data"
        get_indicators.invoke({"symbol": "AAPL", "indicator": "rsi", "curr_date": "2025-01-15", "look_back_days": 60})
        mock_route.assert_called_once_with("get_indicators", "AAPL", "rsi", "2025-01-15", 60)

    @patch(PATCH)
    def test_empty_indicator_ignored(self, mock_route):
        from tradingagents.agents.utils.technical_indicators_tools import get_indicators
        mock_route.return_value = "data"
        get_indicators.invoke({"symbol": "AAPL", "indicator": "rsi, , ", "curr_date": "2025-01-15"})
        assert mock_route.call_count == 1
