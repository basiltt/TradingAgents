"""Tests for tradingagents.dataflows.stockstats_utils — Phase 1 unit tests."""

import os
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


class TestYfRetry:
    def test_success_on_first_try(self):
        from tradingagents.dataflows.stockstats_utils import yf_retry
        result = yf_retry(lambda: "ok")
        assert result == "ok"

    @patch("tradingagents.dataflows.stockstats_utils.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep):
        from yfinance.exceptions import YFRateLimitError
        from tradingagents.dataflows.stockstats_utils import yf_retry
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise YFRateLimitError()
            return "ok"

        result = yf_retry(flaky, max_retries=3, base_delay=0.01)
        assert result == "ok"

    @patch("tradingagents.dataflows.stockstats_utils.time.sleep")
    def test_exhausts_retries(self, mock_sleep):
        from yfinance.exceptions import YFRateLimitError
        from tradingagents.dataflows.stockstats_utils import yf_retry
        with pytest.raises(YFRateLimitError):
            yf_retry(lambda: (_ for _ in ()).throw(YFRateLimitError()), max_retries=1, base_delay=0.01)

    def test_non_rate_limit_propagates(self):
        from tradingagents.dataflows.stockstats_utils import yf_retry
        with pytest.raises(ValueError):
            yf_retry(lambda: (_ for _ in ()).throw(ValueError("bad")))


class TestCleanDataframe:
    def test_drops_invalid_dates(self):
        from tradingagents.dataflows.stockstats_utils import _clean_dataframe
        df = pd.DataFrame({
            "Date": ["2025-01-10", "not-a-date"],
            "Close": [100.0, 200.0],
        })
        result = _clean_dataframe(df)
        assert len(result) == 1

    def test_drops_nan_close(self):
        from tradingagents.dataflows.stockstats_utils import _clean_dataframe
        df = pd.DataFrame({
            "Date": ["2025-01-10", "2025-01-11"],
            "Close": [100.0, None],
        })
        result = _clean_dataframe(df)
        assert len(result) == 1

    def test_fills_price_gaps(self):
        from tradingagents.dataflows.stockstats_utils import _clean_dataframe
        df = pd.DataFrame({
            "Date": ["2025-01-10", "2025-01-11"],
            "Open": [None, 100.0],
            "High": [110.0, None],
            "Low": [90.0, 95.0],
            "Close": [105.0, 102.0],
            "Volume": [1000, 2000],
        })
        result = _clean_dataframe(df)
        assert result["Open"].notna().all()
        assert result["High"].notna().all()


class TestFilterFinancialsByDate:
    def test_empty_date_returns_as_is(self):
        from tradingagents.dataflows.stockstats_utils import filter_financials_by_date
        df = pd.DataFrame({"A": [1]}, index=["2025-12-31"])
        result = filter_financials_by_date(df, "")
        assert len(result.columns) == 1

    def test_empty_df_returns_as_is(self):
        from tradingagents.dataflows.stockstats_utils import filter_financials_by_date
        df = pd.DataFrame()
        result = filter_financials_by_date(df, "2025-01-01")
        assert result.empty

    def test_filters_future_columns(self):
        from tradingagents.dataflows.stockstats_utils import filter_financials_by_date
        df = pd.DataFrame(
            {"Revenue": [100, 200]},
            index=["row1", "row2"],
        )
        df.columns = pd.DatetimeIndex(["2024-12-31"])
        df2 = pd.DataFrame(
            [[100, 200], [300, 400]],
            columns=["2024-12-31", "2025-06-30"],
        )
        result = filter_financials_by_date(df2, "2025-01-01")
        assert "2024-12-31" in result.columns
        assert "2025-06-30" not in result.columns


class TestLoadOhlcv:
    @patch("tradingagents.dataflows.stockstats_utils.yf_retry")
    @patch("tradingagents.dataflows.stockstats_utils.get_config")
    def test_downloads_and_caches(self, mock_config, mock_retry):
        from tradingagents.dataflows.stockstats_utils import load_ohlcv
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_config.return_value = {"data_cache_dir": tmpdir}
            df = pd.DataFrame({
                "Date": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "Open": [100, 101, 102],
                "High": [105, 106, 107],
                "Low": [98, 99, 100],
                "Close": [104, 105, 106],
                "Volume": [1000, 2000, 3000],
            })
            mock_retry.return_value = df.copy()
            # Mock reset_index since yf.download returns index-based
            mock_retry.return_value.reset_index = MagicMock(return_value=df.copy())
            result = load_ohlcv("AAPL", "2025-01-09")
            assert len(result) <= 3

    @patch("tradingagents.dataflows.stockstats_utils.get_config")
    def test_reads_from_cache(self, mock_config):
        from tradingagents.dataflows.stockstats_utils import load_ohlcv
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_config.return_value = {"data_cache_dir": tmpdir}
            df = pd.DataFrame({
                "Date": ["2025-01-10"],
                "Open": [100],
                "High": [105],
                "Low": [98],
                "Close": [104],
                "Volume": [1000],
            })
            # Write a cache file matching the pattern
            today = pd.Timestamp.today()
            start = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
            end = today.strftime("%Y-%m-%d")
            path = os.path.join(tmpdir, f"AAPL-YFin-data-{start}-{end}.csv")
            df.to_csv(path, index=False)
            result = load_ohlcv("AAPL", "2025-01-10")
            assert len(result) == 1


class TestStockstatsUtilsGetStockStats:
    @patch("tradingagents.dataflows.stockstats_utils.wrap")
    @patch("tradingagents.dataflows.stockstats_utils.load_ohlcv")
    def test_happy_path(self, mock_load, mock_wrap):
        from tradingagents.dataflows.stockstats_utils import StockstatsUtils
        df = pd.DataFrame({
            "Date": [pd.Timestamp("2025-01-10")],
            "Close": [150.0],
            "rsi": [55.0],
        })
        mock_load.return_value = df.copy()
        wrapped = df.copy()
        mock_wrap.return_value = wrapped
        result = StockstatsUtils.get_stock_stats("AAPL", "rsi", "2025-01-10")
        assert result == 55.0

    @patch("tradingagents.dataflows.stockstats_utils.wrap")
    @patch("tradingagents.dataflows.stockstats_utils.load_ohlcv")
    def test_non_trading_day(self, mock_load, mock_wrap):
        from tradingagents.dataflows.stockstats_utils import StockstatsUtils
        df = pd.DataFrame({
            "Date": [pd.Timestamp("2025-01-09")],
            "Close": [150.0],
            "rsi": [55.0],
        })
        mock_load.return_value = df.copy()
        mock_wrap.return_value = df.copy()
        result = StockstatsUtils.get_stock_stats("AAPL", "rsi", "2025-01-10")
        assert "Not a trading day" in str(result)
