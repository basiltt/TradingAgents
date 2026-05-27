"""Tests for order book WebSocket client and sweep detection."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.ai_manager_orderbook import OrderBookMonitor, SweepDetector


class TestSweepDetector:
    def test_no_sweep_on_normal_trade(self):
        detector = SweepDetector(confidence_threshold=0.5)
        detector.update_trade({"price": 67000.0, "size": 0.1, "side": "Sell", "time": 1000})
        result = detector.check_sweep(my_sl=66500.0, my_side="Buy", current_price=67000.0)
        assert result is None

    def test_sweep_detected_on_aggressive_volume(self):
        detector = SweepDetector(confidence_threshold=0.5)
        for i in range(20):
            detector.update_trade({"price": 66600.0 - i * 5, "size": 2.0, "side": "Sell", "time": 1000 + i * 100})
        detector._avg_volume_30s = 1.0
        result = detector.check_sweep(my_sl=66500.0, my_side="Buy", current_price=66520.0)
        assert result is not None
        assert result["confidence"] >= 0.5
        assert result["direction"] == "long_hunt"

    def test_sweep_not_targeting_my_position(self):
        detector = SweepDetector(confidence_threshold=0.5)
        for i in range(20):
            detector.update_trade({"price": 70000.0 + i * 5, "size": 2.0, "side": "Buy", "time": 1000 + i * 100})
        detector._avg_volume_30s = 1.0
        result = detector.check_sweep(my_sl=66500.0, my_side="Buy", current_price=67000.0)
        assert result is None or result.get("targets_my_position") is False


class TestOrderBookMonitor:
    def test_compute_imbalance(self):
        monitor = OrderBookMonitor.__new__(OrderBookMonitor)
        monitor._bids = [(67000, 5.0), (66990, 3.0), (66980, 2.0)]
        monitor._asks = [(67010, 2.0), (67020, 1.5), (67030, 1.0)]
        imbalance = monitor._compute_imbalance(levels=3)
        assert imbalance > 1.0

    def test_find_clusters(self):
        monitor = OrderBookMonitor.__new__(OrderBookMonitor)
        monitor._bids = [(67000, 10.0), (66999, 0.5), (66998, 0.3), (66500, 8.0)]
        monitor._asks = [(67010, 0.5), (67500, 12.0)]
        clusters = monitor._find_clusters(side="bid", threshold_multiplier=3.0)
        assert len(clusters) >= 1
        assert clusters[0]["volume"] >= 8.0

    def test_get_snapshot_empty(self):
        monitor = OrderBookMonitor.__new__(OrderBookMonitor)
        monitor._bids = []
        monitor._asks = []
        monitor._sweep_detector = SweepDetector(confidence_threshold=0.5)
        ob_snapshot, sweep = monitor.get_snapshot(my_sl=None, my_side="Buy", current_price=67000.0)
        assert ob_snapshot["imbalance_ratio"] == 1.0
        assert ob_snapshot["spread_bps"] == 0.0
        assert sweep is None
