"""Tests for backend.routers.symbols — Phase 1 unit tests."""

from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.symbols import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestListSymbols:
    @patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["ETHUSDT", "BTCUSDT"])
    def test_crypto_returns_sorted(self, mock_syms):
        r = client.get("/symbols?asset_type=crypto")
        assert r.status_code == 200
        assert r.json()["symbols"] == ["BTCUSDT", "ETHUSDT"]

    @patch("tradingagents.dataflows.bybit_data.get_valid_symbols", return_value=["BTCUSDT"])
    def test_default_is_crypto(self, mock_syms):
        r = client.get("/symbols")
        assert r.status_code == 200
        assert r.json()["symbols"] == ["BTCUSDT"]

    def test_stock_returns_empty(self):
        r = client.get("/symbols?asset_type=stock")
        assert r.status_code == 200
        assert r.json()["symbols"] == []

    def test_invalid_asset_type_rejected(self):
        r = client.get("/symbols?asset_type=forex")
        assert r.status_code == 422
