"""Tests for tradingagents.dataflows.y_finance — Phase 1 unit tests."""

from datetime import datetime
from unittest.mock import patch, MagicMock, PropertyMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# get_YFin_data_online
# ---------------------------------------------------------------------------


class TestGetYFinDataOnline:
    def _import(self):
        from tradingagents.dataflows.y_finance import get_YFin_data_online
        return get_YFin_data_online

    def test_invalid_start_date_raises(self):
        fn = self._import()
        with pytest.raises(ValueError):
            fn("AAPL", "not-a-date", "2025-01-01")

    def test_invalid_end_date_raises(self):
        fn = self._import()
        with pytest.raises(ValueError):
            fn("AAPL", "2025-01-01", "bad")

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_empty_data_returns_message(self, mock_ticker_cls, mock_retry):
        fn = self._import()
        mock_retry.return_value = pd.DataFrame()
        result = fn("AAPL", "2025-01-01", "2025-01-05")
        assert "No data found" in result
        assert "AAPL" in result

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_happy_path_returns_csv(self, mock_ticker_cls, mock_retry):
        fn = self._import()
        idx = pd.DatetimeIndex(["2025-01-02", "2025-01-03"], tz="US/Eastern")
        df = pd.DataFrame(
            {"Open": [150.123, 151.456], "High": [155.0, 156.0],
             "Low": [149.0, 150.0], "Close": [154.789, 155.321],
             "Volume": [1000, 2000]},
            index=idx,
        )
        mock_retry.return_value = df
        result = fn("aapl", "2025-01-01", "2025-01-05")
        assert "AAPL" in result
        assert "Total records: 2" in result
        assert "154.79" in result  # rounded

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_no_timezone_data_still_works(self, mock_ticker_cls, mock_retry):
        fn = self._import()
        idx = pd.DatetimeIndex(["2025-01-02"])
        df = pd.DataFrame({"Open": [100.0], "Close": [101.0]}, index=idx)
        mock_retry.return_value = df
        result = fn("SPY", "2025-01-01", "2025-01-05")
        assert "SPY" in result


# ---------------------------------------------------------------------------
# get_stock_stats_indicators_window
# ---------------------------------------------------------------------------


class TestGetStockStatsIndicatorsWindow:
    def _import(self):
        from tradingagents.dataflows.y_finance import get_stock_stats_indicators_window
        return get_stock_stats_indicators_window

    def test_unsupported_indicator_raises(self):
        fn = self._import()
        with pytest.raises(ValueError, match="not supported"):
            fn("AAPL", "nonexistent_indicator", "2025-01-10", 5)

    @patch("tradingagents.dataflows.y_finance._get_stock_stats_bulk")
    def test_happy_path_bulk(self, mock_bulk):
        fn = self._import()
        mock_bulk.return_value = {
            "2025-01-10": "50.5",
            "2025-01-09": "49.3",
            "2025-01-08": "N/A",
        }
        result = fn("AAPL", "rsi", "2025-01-10", 3)
        assert "rsi" in result.lower()
        assert "2025-01-10" in result
        assert "50.5" in result
        assert "N/A" in result

    @patch("tradingagents.dataflows.y_finance._get_stock_stats_bulk", side_effect=RuntimeError("fail"))
    @patch("tradingagents.dataflows.y_finance.get_stockstats_indicator", return_value="42.0")
    def test_fallback_on_bulk_failure(self, mock_single, mock_bulk):
        fn = self._import()
        result = fn("AAPL", "rsi", "2025-01-10", 2)
        assert "42.0" in result
        assert mock_single.call_count >= 1

    @patch("tradingagents.dataflows.y_finance._get_stock_stats_bulk")
    def test_non_trading_day_shows_na(self, mock_bulk):
        fn = self._import()
        mock_bulk.return_value = {"2025-01-10": "50.0"}
        result = fn("AAPL", "rsi", "2025-01-10", 1)
        assert "Not a trading day" in result or "50.0" in result


# ---------------------------------------------------------------------------
# _get_stock_stats_bulk
# ---------------------------------------------------------------------------


class TestGetStockStatsBulk:
    @patch("tradingagents.dataflows.y_finance.load_ohlcv")
    @patch("stockstats.wrap")
    def test_nan_mapped_to_na(self, mock_wrap, mock_load):
        from tradingagents.dataflows.y_finance import _get_stock_stats_bulk
        df = pd.DataFrame({
            "Date": [pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-09")],
            "rsi": [50.0, float("nan")],
        })
        mock_load.return_value = df.copy()
        mock_wrap.return_value = df
        result = _get_stock_stats_bulk("AAPL", "rsi", "2025-01-10")
        assert result["2025-01-09"] == "N/A"
        assert result["2025-01-10"] == "50.0"


# ---------------------------------------------------------------------------
# get_stockstats_indicator
# ---------------------------------------------------------------------------


class TestGetStockstatsIndicator:
    @patch("tradingagents.dataflows.y_finance.StockstatsUtils")
    def test_happy_path(self, mock_utils):
        from tradingagents.dataflows.y_finance import get_stockstats_indicator
        mock_utils.get_stock_stats.return_value = 42.5
        result = get_stockstats_indicator("AAPL", "rsi", "2025-01-10")
        assert result == "42.5"

    @patch("tradingagents.dataflows.y_finance.StockstatsUtils")
    def test_exception_returns_empty(self, mock_utils):
        from tradingagents.dataflows.y_finance import get_stockstats_indicator
        mock_utils.get_stock_stats.side_effect = RuntimeError("boom")
        result = get_stockstats_indicator("AAPL", "rsi", "2025-01-10")
        assert result == ""


# ---------------------------------------------------------------------------
# get_fundamentals
# ---------------------------------------------------------------------------


class TestGetFundamentals:
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_happy_path(self, mock_ticker_cls, mock_retry):
        from tradingagents.dataflows.y_finance import get_fundamentals
        mock_retry.return_value = {"longName": "Apple Inc.", "sector": "Technology", "marketCap": 3000000000000}
        result = get_fundamentals("AAPL")
        assert "Apple Inc." in result
        assert "Technology" in result

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_empty_info(self, mock_ticker_cls, mock_retry):
        from tradingagents.dataflows.y_finance import get_fundamentals
        mock_retry.return_value = {}
        result = get_fundamentals("FAKE")
        assert "No fundamentals data" in result

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_none_values_filtered(self, mock_ticker_cls, mock_retry):
        from tradingagents.dataflows.y_finance import get_fundamentals
        mock_retry.return_value = {"longName": "Test", "sector": None, "marketCap": 100}
        result = get_fundamentals("TEST")
        assert "Sector" not in result
        assert "Market Cap" in result

    @patch("tradingagents.dataflows.y_finance.yf.Ticker", side_effect=RuntimeError("network"))
    def test_exception_returns_error(self, mock_ticker_cls):
        from tradingagents.dataflows.y_finance import get_fundamentals
        result = get_fundamentals("AAPL")
        assert "Error retrieving fundamentals" in result


# ---------------------------------------------------------------------------
# get_balance_sheet / get_cashflow / get_income_statement
# ---------------------------------------------------------------------------


class TestFinancialStatements:
    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({"Revenue": [100, 200]}, index=["2024-12-31", "2024-09-30"])

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: d)
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_balance_sheet_quarterly(self, mock_cls, mock_retry, mock_filter, sample_df):
        from tradingagents.dataflows.y_finance import get_balance_sheet
        mock_retry.return_value = sample_df
        result = get_balance_sheet("AAPL", freq="quarterly")
        assert "Balance Sheet" in result
        assert "quarterly" in result

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: d)
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_balance_sheet_annual(self, mock_cls, mock_retry, mock_filter, sample_df):
        from tradingagents.dataflows.y_finance import get_balance_sheet
        mock_retry.return_value = sample_df
        result = get_balance_sheet("AAPL", freq="annual")
        assert "Balance Sheet" in result

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: pd.DataFrame())
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_balance_sheet_empty(self, mock_cls, mock_retry, mock_filter):
        from tradingagents.dataflows.y_finance import get_balance_sheet
        mock_retry.return_value = pd.DataFrame()
        result = get_balance_sheet("FAKE")
        assert "No balance sheet data" in result

    @patch("tradingagents.dataflows.y_finance.yf.Ticker", side_effect=RuntimeError("err"))
    def test_balance_sheet_exception(self, mock_cls):
        from tradingagents.dataflows.y_finance import get_balance_sheet
        result = get_balance_sheet("AAPL")
        assert "Error retrieving balance sheet" in result

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: d)
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_cashflow_happy(self, mock_cls, mock_retry, mock_filter, sample_df):
        from tradingagents.dataflows.y_finance import get_cashflow
        mock_retry.return_value = sample_df
        result = get_cashflow("AAPL")
        assert "Cash Flow" in result

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: pd.DataFrame())
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_cashflow_empty(self, mock_cls, mock_retry, mock_filter):
        from tradingagents.dataflows.y_finance import get_cashflow
        mock_retry.return_value = pd.DataFrame()
        result = get_cashflow("FAKE")
        assert "No cash flow data" in result

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: d)
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_income_statement_happy(self, mock_cls, mock_retry, mock_filter, sample_df):
        from tradingagents.dataflows.y_finance import get_income_statement
        mock_retry.return_value = sample_df
        result = get_income_statement("AAPL")
        assert "Income Statement" in result

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date", side_effect=lambda d, c: pd.DataFrame())
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_income_statement_empty(self, mock_cls, mock_retry, mock_filter):
        from tradingagents.dataflows.y_finance import get_income_statement
        mock_retry.return_value = pd.DataFrame()
        result = get_income_statement("FAKE")
        assert "No income statement data" in result


# ---------------------------------------------------------------------------
# get_insider_transactions
# ---------------------------------------------------------------------------


class TestGetInsiderTransactions:
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_happy_path(self, mock_cls, mock_retry):
        from tradingagents.dataflows.y_finance import get_insider_transactions
        mock_retry.return_value = pd.DataFrame({"Shares": [100], "Value": [5000]})
        result = get_insider_transactions("AAPL")
        assert "Insider Transactions" in result

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_none_data(self, mock_cls, mock_retry):
        from tradingagents.dataflows.y_finance import get_insider_transactions
        mock_retry.return_value = None
        result = get_insider_transactions("FAKE")
        assert "No insider transactions" in result

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_empty_data(self, mock_cls, mock_retry):
        from tradingagents.dataflows.y_finance import get_insider_transactions
        mock_retry.return_value = pd.DataFrame()
        result = get_insider_transactions("FAKE")
        assert "No insider transactions" in result

    @patch("tradingagents.dataflows.y_finance.yf.Ticker", side_effect=RuntimeError("err"))
    def test_exception(self, mock_cls):
        from tradingagents.dataflows.y_finance import get_insider_transactions
        result = get_insider_transactions("AAPL")
        assert "Error retrieving insider transactions" in result
