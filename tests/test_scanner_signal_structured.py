"""Unit tests for the structured signal extraction path in scanner_service."""

import asyncio
import json as _json
from unittest.mock import AsyncMock, MagicMock


def _extract(pm_data, trader_data=None):
    from backend.services.scanner_service import _extract_signal_from_structured
    return _extract_signal_from_structured(pm_data, trader_data or {})


def _direction(rating):
    from backend.services.scanner_service import _rating_to_direction
    return _rating_to_direction(rating)


class TestRatingToDirection:
    def test_buy(self):           assert _direction("Buy") == "buy"
    def test_overweight(self):    assert _direction("Overweight") == "buy"
    def test_hold(self):          assert _direction("Hold") == "hold"
    def test_underweight(self):   assert _direction("Underweight") == "sell"
    def test_sell(self):          assert _direction("Sell") == "sell"
    def test_unknown_defaults_to_hold(self): assert _direction("Unknown") == "hold"
    def test_case_insensitive(self): assert _direction("BUY") == "buy"


class TestExtractSignalFromStructured:
    def test_buy_high_confidence(self):
        result = _extract({"rating": "Buy", "confidence": 8})
        assert result["direction"] == "buy"
        assert result["confidence"] == "high"
        assert result["score"] == 8

    def test_sell_moderate_confidence(self):
        result = _extract({"rating": "Sell", "confidence": 5})
        assert result["direction"] == "sell"
        assert result["confidence"] == "moderate"
        assert result["score"] == -5

    def test_overweight_uses_buy(self):
        result = _extract({"rating": "Overweight", "confidence": 7})
        assert result["direction"] == "buy"
        assert result["score"] == 7

    def test_underweight_uses_sell(self):
        result = _extract({"rating": "Underweight", "confidence": 4})
        assert result["direction"] == "sell"
        assert result["score"] == -4

    def test_hold_always_zero(self):
        result = _extract({"rating": "Hold", "confidence": 9})
        assert result["direction"] == "hold"
        assert result["score"] == 0
        assert result["confidence"] == "none"

    def test_none_confidence_defaults_to_5(self):
        result = _extract({"rating": "Buy", "confidence": None})
        assert result["score"] == 5
        assert result["confidence"] == "moderate"

    def test_missing_confidence_falls_back_to_trader(self):
        result = _extract({"rating": "Buy"}, {"confidence": 9})
        assert result["score"] == 9
        assert result["confidence"] == "high"

    def test_confidence_clamped_at_10(self):
        result = _extract({"rating": "Buy", "confidence": 99})
        assert result["score"] == 10

    def test_confidence_clamped_at_1(self):
        result = _extract({"rating": "Sell", "confidence": -5})
        assert result["score"] == -1

    def test_low_confidence_label(self):
        result = _extract({"rating": "Buy", "confidence": 2})
        assert result["confidence"] == "low"
        assert result["score"] == 2

    def test_confidence_zero_treated_as_present_not_absent(self):
        # confidence=0 must not fall through to trader's confidence
        result = _extract({"rating": "Buy", "confidence": 0}, {"confidence": 9})
        # 0 is clamped to 1 (min), not replaced by trader's 9
        assert result["score"] == 1
        assert result["confidence"] == "low"



def _make_scanner(snapshot_reports):
    """Return a ScannerService with a mocked analysis service that yields the given reports."""
    from backend.services.scanner_service import ScannerService

    analysis = MagicMock()
    analysis.get_snapshot = AsyncMock(return_value={"reports": snapshot_reports})
    analysis.get_run = AsyncMock(return_value={"status": "completed"})
    scanner = ScannerService(analysis_service=analysis, db=None)
    scanner._scans["scan-1"] = {
        "status": "running", "completed": 0, "failed": 0, "results": [], "cancel": False
    }
    return scanner


class TestCollectResultStructuredPath:
    def test_uses_pm_signal_json_when_present(self):
        pm_json = _json.dumps({"rating": "Buy", "confidence": 8})
        trader_json = _json.dumps({"action": "Buy", "confidence": 7})
        scanner = _make_scanner({
            "_pm_signal": pm_json,
            "_trader_signal": trader_json,
            "portfolio_manager": "some markdown that would confuse the regex",
        })
        run = {"status": "completed"}
        asyncio.run(
            scanner._collect_result("scan-1", "BTCUSDT", "run-99", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert len(results) == 1
        r = results[0]
        assert r["direction"] == "buy"
        assert r["confidence"] == "high"
        assert r["score"] == 8
        assert r["signal_source"] == "structured"

    def test_falls_back_to_regex_when_no_pm_signal_key(self):
        scanner = _make_scanner({
            "portfolio_manager": "Final decision: APPROVE. We go long. Confidence: 7/10.",
        })
        run = {"status": "completed"}
        asyncio.run(
            scanner._collect_result("scan-1", "ETHUSDT", "run-100", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert len(results) == 1
        r = results[0]
        assert r["direction"] == "buy"
        assert r["signal_source"] == "regex_fallback"

    def test_failed_run_returns_hold_regardless(self):
        pm_json = _json.dumps({"rating": "Buy", "confidence": 9})
        scanner = _make_scanner({"_pm_signal": pm_json})
        run = {"status": "failed"}
        asyncio.run(
            scanner._collect_result("scan-1", "SOLUSDT", "run-101", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert results[0]["direction"] == "hold"
        assert results[0]["score"] == 0
        assert results[0]["signal_source"] == "none"

    def test_trader_signal_only_quick_trade_long(self):
        """In quick_trade mode, only _trader_signal exists (no PM). Parse it directly."""
        trader_json = _json.dumps({"trade_type": "Long", "confidence": 7})
        scanner = _make_scanner({
            "_trader_signal": trader_json,
            "trader": "some narrative text",
        })
        run = {"status": "completed"}
        asyncio.run(
            scanner._collect_result("scan-1", "BTCUSDT", "run-200", run)
        )
        results = scanner._scans["scan-1"]["results"]
        assert len(results) == 1
        r = results[0]
        assert r["direction"] == "buy"
        assert r["confidence"] == "high"
        assert r["score"] == 7
        assert r["signal_source"] == "structured"

    def test_trader_signal_only_quick_trade_short(self):
        trader_json = _json.dumps({"trade_type": "Short", "confidence": 6})
        scanner = _make_scanner({
            "_trader_signal": trader_json,
        })
        run = {"status": "completed"}
        asyncio.run(
            scanner._collect_result("scan-1", "ETHUSDT", "run-201", run)
        )
        results = scanner._scans["scan-1"]["results"]
        r = results[0]
        assert r["direction"] == "sell"
        assert r["confidence"] == "moderate"
        assert r["score"] == -6
        assert r["signal_source"] == "structured"

    def test_trader_signal_only_no_trade(self):
        trader_json = _json.dumps({"trade_type": "No Trade", "confidence": 3})
        scanner = _make_scanner({
            "_trader_signal": trader_json,
        })
        run = {"status": "completed"}
        asyncio.run(
            scanner._collect_result("scan-1", "SOLUSDT", "run-202", run)
        )
        results = scanner._scans["scan-1"]["results"]
        r = results[0]
        assert r["direction"] == "hold"
        assert r["score"] == 0
        assert r["signal_source"] == "structured"

    def test_trader_signal_malformed_falls_back_to_regex(self):
        """If _trader_signal JSON lacks trade_type, fall back to regex on narrative."""
        trader_json = _json.dumps({"action": "buy", "confidence": 8})
        scanner = _make_scanner({
            "_trader_signal": trader_json,
            "portfolio_manager": "Final decision: APPROVE. We go long. Confidence: 8/10.",
        })
        run = {"status": "completed"}
        asyncio.run(
            scanner._collect_result("scan-1", "BTCUSDT", "run-203", run)
        )
        results = scanner._scans["scan-1"]["results"]
        r = results[0]
        assert r["signal_source"] == "regex_fallback"
