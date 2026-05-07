"""Tests for agent tool wrappers — coingecko, fundamentals, news, core stock."""

from unittest.mock import patch, MagicMock


ROUTE_PATCH = "tradingagents.agents.utils.{module}.route_to_vendor"


class TestFundamentalTools:
    @patch("tradingagents.agents.utils.fundamental_data_tools.route_to_vendor", return_value="fund data")
    def test_get_fundamentals(self, mock_route):
        from tradingagents.agents.utils.fundamental_data_tools import get_fundamentals
        result = get_fundamentals.invoke({"ticker": "AAPL", "curr_date": "2025-01-15"})
        assert result == "fund data"

    @patch("tradingagents.agents.utils.fundamental_data_tools.route_to_vendor", return_value="bs data")
    def test_get_balance_sheet(self, mock_route):
        from tradingagents.agents.utils.fundamental_data_tools import get_balance_sheet
        result = get_balance_sheet.invoke({"ticker": "AAPL"})
        assert result == "bs data"

    @patch("tradingagents.agents.utils.fundamental_data_tools.route_to_vendor", return_value="cf data")
    def test_get_cashflow(self, mock_route):
        from tradingagents.agents.utils.fundamental_data_tools import get_cashflow
        result = get_cashflow.invoke({"ticker": "AAPL"})
        assert result == "cf data"

    @patch("tradingagents.agents.utils.fundamental_data_tools.route_to_vendor", return_value="is data")
    def test_get_income_statement(self, mock_route):
        from tradingagents.agents.utils.fundamental_data_tools import get_income_statement
        result = get_income_statement.invoke({"ticker": "AAPL"})
        assert result == "is data"


class TestNewsTools:
    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor", return_value="news")
    def test_get_news(self, mock_route):
        from tradingagents.agents.utils.news_data_tools import get_news
        result = get_news.invoke({"ticker": "AAPL", "start_date": "2025-01-01", "end_date": "2025-01-15"})
        assert result == "news"

    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor", return_value="global")
    def test_get_global_news(self, mock_route):
        from tradingagents.agents.utils.news_data_tools import get_global_news
        result = get_global_news.invoke({"curr_date": "2025-01-15"})
        assert result == "global"

    @patch("tradingagents.agents.utils.news_data_tools.route_to_vendor", return_value="insider")
    def test_get_insider_transactions(self, mock_route):
        from tradingagents.agents.utils.news_data_tools import get_insider_transactions
        result = get_insider_transactions.invoke({"ticker": "AAPL"})
        assert result == "insider"


class TestCoreStockTools:
    @patch("tradingagents.agents.utils.core_stock_tools.route_to_vendor", return_value="stock data")
    def test_get_stock_data(self, mock_route):
        from tradingagents.agents.utils.core_stock_tools import get_stock_data
        result = get_stock_data.invoke({"symbol": "AAPL", "start_date": "2025-01-01", "end_date": "2025-01-15"})
        assert result == "stock data"


class TestCoingeckoTools:
    @patch("tradingagents.agents.utils.coingecko_tools.get_bybit_price_changes", return_value={"24h": 1.5, "7d": -2.0})
    @patch("tradingagents.agents.utils.coingecko_tools.get_coingecko_fundamentals_only", return_value="market data")
    def test_market_data_success(self, mock_cg, mock_bybit):
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        tools = make_coingecko_tools()
        market_tool = next(t for t in tools if t.name == "get_crypto_market_data")
        result = market_tool.invoke({"symbol": "BTCUSDT"})
        assert "market data" in result
        assert "<data>" in result

    @patch("tradingagents.agents.utils.coingecko_tools.get_bybit_price_changes", side_effect=Exception("fail"))
    @patch("tradingagents.agents.utils.coingecko_tools.get_coingecko_fundamentals_only", side_effect=Exception("fail"))
    def test_market_data_error(self, mock_cg, mock_bybit):
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        tools = make_coingecko_tools()
        market_tool = next(t for t in tools if t.name == "get_crypto_market_data")
        result = market_tool.invoke({"symbol": "BTCUSDT"})
        assert "unavailable" in result.lower()

    @patch("tradingagents.agents.utils.coingecko_tools.get_coingecko_community_data", return_value="social data")
    def test_community_data_success(self, mock_cg):
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        tools = make_coingecko_tools()
        community_tool = next(t for t in tools if t.name == "get_crypto_community_data")
        result = community_tool.invoke({"symbol": "BTCUSDT"})
        assert "social data" in result

    @patch("tradingagents.agents.utils.coingecko_tools.get_coingecko_community_data", side_effect=Exception("fail"))
    def test_community_data_error(self, mock_cg):
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        tools = make_coingecko_tools()
        community_tool = next(t for t in tools if t.name == "get_crypto_community_data")
        result = community_tool.invoke({"symbol": "BTCUSDT"})
        assert "unavailable" in result.lower()

    @patch("tradingagents.agents.utils.coingecko_tools.get_bybit_derivatives_summary", return_value="derivatives data")
    def test_derivatives_data_success(self, mock_bybit):
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        tools = make_coingecko_tools()
        deriv_tool = next(t for t in tools if t.name == "get_crypto_derivatives_data")
        result = deriv_tool.invoke({"symbol": "BTCUSDT"})
        assert "derivatives data" in result
        assert "<data>" in result

    @patch("tradingagents.agents.utils.coingecko_tools.get_bybit_derivatives_summary", side_effect=Exception("fail"))
    def test_derivatives_data_error(self, mock_bybit):
        from tradingagents.agents.utils.coingecko_tools import make_coingecko_tools
        tools = make_coingecko_tools()
        deriv_tool = next(t for t in tools if t.name == "get_crypto_derivatives_data")
        result = deriv_tool.invoke({"symbol": "BTCUSDT"})
        assert "unavailable" in result.lower()

    def test_sanitize_truncation(self):
        from tradingagents.agents.utils.coingecko_tools import _sanitize
        long_str = "a" * 60000
        result = _sanitize(long_str)
        assert "[truncated]" in result
        assert "<data>" in result
