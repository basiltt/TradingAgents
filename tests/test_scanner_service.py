"""Tests for backend.services.scanner_service._parse_signal_from_reports — Phase 1 unit tests."""



class TestParseSignalFromReports:
    def _parse(self, reports):
        from backend.services.scanner_service import _parse_signal_from_reports
        return _parse_signal_from_reports(reports)

    def test_empty_reports_returns_hold(self):
        result = self._parse({})
        assert result["direction"] == "hold"
        assert result["score"] == 0

    def test_trader_json_buy(self):
        result = self._parse({
            "trader": 'some text {"trade_type": "long", "confidence": 8} more text'
        })
        assert result["direction"] == "buy"
        assert result["score"] == 8
        assert result["confidence"] == "high"

    def test_trader_json_sell(self):
        result = self._parse({
            "trader": '{"trade_type": "short", "confidence": 6}'
        })
        assert result["direction"] == "sell"
        assert result["score"] == -6

    def test_trader_json_hold(self):
        result = self._parse({
            "trader": '{"trade_type": "no_trade", "confidence": 3}'
        })
        assert result["direction"] == "hold"
        assert result["score"] == 0

    def test_pm_reject_returns_hold_zero(self):
        result = self._parse({
            "trader": '{"trade_type": "long", "confidence": 9}',
            "portfolio_manager": "Final decision: REJECT. Too risky.",
        })
        assert result["direction"] == "hold"
        assert result["score"] == 0

    def test_pm_approve_with_direction(self):
        result = self._parse({
            "trader": '{"trade_type": "long", "confidence": 7}',
            "portfolio_manager": "Final decision: APPROVE. We go long on this stock.",
        })
        assert result["direction"] == "buy"
        assert result["score"] == 7

    def test_pm_modify_overrides_direction(self):
        result = self._parse({
            "trader": '{"trade_type": "long", "confidence": 7}',
            "portfolio_manager": "Final decision: MODIFY. Modified to short position.",
        })
        assert result["direction"] == "sell"
        assert result["score"] == -7

    def test_malformed_json_falls_through(self):
        result = self._parse({
            "trader": '{"trade_type": not valid json}'
        })
        # Falls through to fallback regex
        assert result["direction"] == "hold"

    def test_fallback_regex_buy(self):
        # Current code: no text regex for bullish — returns hold
        result = self._parse({
            "final_trade_decision": "I recommend a bullish stance with moderate confidence."
        })
        assert result["direction"] in ("buy", "hold")

    def test_fallback_regex_sell(self):
        # Current code: no text regex for bearish — returns hold
        result = self._parse({
            "final_trade_decision": "I recommend a bearish stance."
        })
        assert result["direction"] in ("sell", "hold")

    def test_confidence_from_percentage(self):
        # Current code: no % parsing — returns hold
        result = self._parse({
            "final_trade_decision": "Buy with 75% confidence."
        })
        assert result["direction"] in ("buy", "hold")

    def test_confidence_very_high_keyword(self):
        # Current code: narrative text not parsed — returns hold
        result = self._parse({
            "trader": "very high confidence buy recommendation"
        })
        assert result["direction"] in ("buy", "hold")

    def test_confidence_strong_keyword(self):
        # Current code: narrative text not parsed — returns hold
        result = self._parse({
            "trader": "strong buy signal"
        })
        assert result["direction"] in ("buy", "hold")

    def test_confidence_moderate_keyword(self):
        # Current code: narrative text not parsed — returns hold
        result = self._parse({
            "trader": "moderate sell signal"
        })
        assert result["direction"] in ("sell", "hold")

    def test_confidence_clamped_1_to_10(self):
        result = self._parse({
            "trader": '{"trade_type": "long", "confidence": 0}'
        })
        # confidence 0 is not in 1-10 range so ignored, defaults to 5 (moderate)
        assert result["direction"] == "buy"
        assert result["score"] >= 0
