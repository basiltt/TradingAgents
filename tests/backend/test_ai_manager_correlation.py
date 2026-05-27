"""Tests for multi-position correlation module."""
import pytest

from backend.services.ai_manager_correlation import CorrelationAnalyzer


class TestCorrelationAnalyzer:
    def test_single_position_no_correlation(self):
        analyzer = CorrelationAnalyzer()
        positions = [{"symbol": "BTCUSDT", "side": "Buy", "positionValue": "1000"}]
        klines = {"BTCUSDT": {"1h": _make_klines(30)}}
        result = analyzer.compute(positions, klines)
        assert result["portfolio_heat"] == 0.0
        assert result["matrix"] == {}
        assert result["clusters"] == []

    def test_high_correlation_detected(self):
        analyzer = CorrelationAnalyzer()
        positions = [
            {"symbol": "BTCUSDT", "side": "Buy", "positionValue": "1000"},
            {"symbol": "ETHUSDT", "side": "Buy", "positionValue": "1000"},
        ]
        btc_klines = _make_uptrend(30)
        eth_klines = _make_uptrend(30)
        klines = {"BTCUSDT": {"1h": btc_klines}, "ETHUSDT": {"1h": eth_klines}}
        result = analyzer.compute(positions, klines)
        assert result["portfolio_heat"] > 0.7
        assert "BTCUSDT:ETHUSDT" in result["matrix"]
        assert result["matrix"]["BTCUSDT:ETHUSDT"] > 0.9

    def test_hedged_positions(self):
        """Test that opposite-direction correlated positions have low risk."""
        analyzer = CorrelationAnalyzer()
        positions = [
            {"symbol": "BTCUSDT", "side": "Buy", "positionValue": "1000"},
            {"symbol": "XYZUSDT", "side": "Sell", "positionValue": "1000"},
        ]
        btc_klines = _make_uptrend(30)
        xyz_klines = _make_uptrend(30)  # Same trend direction
        klines = {"BTCUSDT": {"1h": btc_klines}, "XYZUSDT": {"1h": xyz_klines}}
        result = analyzer.compute(positions, klines)
        # Opposite sides with positive correlation = low heat (hedging)
        assert result["portfolio_heat"] < 0.3

    def test_cluster_detection(self):
        analyzer = CorrelationAnalyzer(correlation_threshold=0.7)
        positions = [
            {"symbol": "BTCUSDT", "side": "Buy", "positionValue": "5000"},
            {"symbol": "ETHUSDT", "side": "Buy", "positionValue": "3000"},
            {"symbol": "SOLUSDT", "side": "Buy", "positionValue": "2000"},
        ]
        klines = {
            "BTCUSDT": {"1h": _make_uptrend(30)},
            "ETHUSDT": {"1h": _make_uptrend(30)},
            "SOLUSDT": {"1h": _make_uptrend(30)},
        }
        result = analyzer.compute(positions, klines)
        assert len(result["clusters"]) >= 1
        cluster = result["clusters"][0]
        assert "symbols" in cluster
        assert "avg_correlation" in cluster
        assert "combined_notional_usd" in cluster

    def test_empty_positions(self):
        analyzer = CorrelationAnalyzer()
        result = analyzer.compute([], {})
        assert result["portfolio_heat"] == 0.0


def _make_uptrend(n):
    return [[i * 3600000, 50000 + i * 100, 50000 + i * 100 + 50, 50000 + i * 100 - 30, 50000 + i * 100 + 40, 100] for i in range(n)]

def _make_downtrend(n):
    return [[i * 3600000, 50000 - i * 100, 50000 - i * 100 + 30, 50000 - i * 100 - 50, 50000 - i * 100 - 40, 100] for i in range(n)]

def _make_klines(n):
    return _make_uptrend(n)
