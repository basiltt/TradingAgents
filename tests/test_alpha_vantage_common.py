"""Tests for tradingagents.dataflows.alpha_vantage_common — Phase 1 unit tests."""

import json
import os
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


class TestGetApiKey:
    def test_key_present(self):
        from tradingagents.dataflows.alpha_vantage_common import get_api_key
        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "test123"}):
            assert get_api_key() == "test123"

    def test_key_missing_raises(self):
        from tradingagents.dataflows.alpha_vantage_common import get_api_key
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ALPHA_VANTAGE_API_KEY", None)
            with pytest.raises(ValueError, match="not set"):
                get_api_key()


class TestFormatDatetimeForApi:
    def test_already_formatted(self):
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api
        assert format_datetime_for_api("20250110T1430") == "20250110T1430"

    def test_yyyy_mm_dd(self):
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api
        assert format_datetime_for_api("2025-01-10") == "20250110T0000"

    def test_yyyy_mm_dd_hhmm(self):
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api
        assert format_datetime_for_api("2025-01-10 14:30") == "20250110T1430"

    def test_datetime_object(self):
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api
        dt = datetime(2025, 1, 10, 14, 30)
        assert format_datetime_for_api(dt) == "20250110T1430"

    def test_unsupported_string(self):
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api
        with pytest.raises(ValueError, match="Unsupported date format"):
            format_datetime_for_api("Jan 10 2025")

    def test_wrong_type(self):
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api
        with pytest.raises(ValueError, match="Date must be string or datetime"):
            format_datetime_for_api(12345)


class TestMakeApiRequest:
    @patch("tradingagents.dataflows.alpha_vantage_common.get_api_key", return_value="testkey")
    @patch("tradingagents.dataflows.alpha_vantage_common.requests.get")
    def test_csv_response(self, mock_get, mock_key):
        from tradingagents.dataflows.alpha_vantage_common import _make_api_request
        mock_resp = MagicMock()
        mock_resp.text = "time,SMA\n2025-01-10,50.0\n"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = _make_api_request("SMA", {"symbol": "AAPL"})
        assert "SMA" in result
        mock_get.assert_called_once()
        call_params = mock_get.call_args[1]["params"]
        assert call_params["function"] == "SMA"
        assert call_params["apikey"] == "testkey"
        assert call_params["source"] == "trading_agents"

    @patch("tradingagents.dataflows.alpha_vantage_common.get_api_key", return_value="testkey")
    @patch("tradingagents.dataflows.alpha_vantage_common.requests.get")
    def test_rate_limit_raises(self, mock_get, mock_key):
        from tradingagents.dataflows.alpha_vantage_common import _make_api_request, AlphaVantageRateLimitError
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"Information": "API rate limit exceeded"})
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        with pytest.raises(AlphaVantageRateLimitError):
            _make_api_request("SMA", {"symbol": "AAPL"})

    @patch("tradingagents.dataflows.alpha_vantage_common.get_api_key", return_value="testkey")
    @patch("tradingagents.dataflows.alpha_vantage_common.requests.get")
    def test_http_error_propagates(self, mock_get, mock_key):
        from tradingagents.dataflows.alpha_vantage_common import _make_api_request
        import requests
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("429")
        mock_get.return_value = mock_resp
        with pytest.raises(requests.HTTPError):
            _make_api_request("SMA", {"symbol": "AAPL"})


class TestFilterCsvByDateRange:
    def test_empty_string(self):
        from tradingagents.dataflows.alpha_vantage_common import _filter_csv_by_date_range
        assert _filter_csv_by_date_range("", "2025-01-01", "2025-01-10") == ""

    def test_valid_csv_filtered(self):
        from tradingagents.dataflows.alpha_vantage_common import _filter_csv_by_date_range
        csv = "time,value\n2025-01-05,10\n2025-01-08,20\n2025-01-15,30\n"
        result = _filter_csv_by_date_range(csv, "2025-01-01", "2025-01-10")
        assert "10" in result
        assert "20" in result
        assert "30" not in result

    def test_malformed_csv_returns_original(self):
        from tradingagents.dataflows.alpha_vantage_common import _filter_csv_by_date_range
        bad = "this is not csv at all"
        result = _filter_csv_by_date_range(bad, "2025-01-01", "2025-01-10")
        assert result.strip() == bad.strip()
