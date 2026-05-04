"""Tests for cli.utils — Phase 1 unit tests."""

import pytest


class TestNormalizeTickerSymbol:
    def test_basic(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("aapl") == "AAPL"

    def test_strips_whitespace(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("  spy  ") == "SPY"

    def test_preserves_suffix(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("cnc.to") == "CNC.TO"

    def test_already_upper(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("GOOG") == "GOOG"


class TestFetchOpenRouterModels:
    def test_success(self):
        from unittest.mock import patch, MagicMock
        from cli.utils import _fetch_openrouter_models
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "model-1", "name": "Model One"},
                {"id": "model-2"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = _fetch_openrouter_models()
        assert result == [("Model One", "model-1"), ("model-2", "model-2")]

    def test_failure_returns_empty(self):
        from unittest.mock import patch
        from cli.utils import _fetch_openrouter_models
        with patch("requests.get", side_effect=Exception("fail")):
            result = _fetch_openrouter_models()
        assert result == []
