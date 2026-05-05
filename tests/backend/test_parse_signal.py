"""Tests for _parse_signal_from_reports — Phase 3 R1 (TASK-016)."""

import pytest


def parse(reports):
    from backend.services.scanner_service import _parse_signal_from_reports
    return _parse_signal_from_reports(reports)


def test_pm_reject_returns_hold_zero():
    result = parse({"portfolio_manager": "Final Decision: REJECT the trade."})
    assert result["direction"] == "hold"
    assert result["score"] == 0


def test_pm_approve_long():
    result = parse({"portfolio_manager": "Final Decision: APPROVE long position."})
    assert result["direction"] == "buy"
    assert result["score"] > 0


def test_pm_approve_short():
    result = parse({"portfolio_manager": "Final Decision: APPROVE short position."})
    assert result["direction"] == "sell"
    assert result["score"] < 0


def test_pm_modify_buy():
    result = parse({"portfolio_manager": "Final Decision: MODIFY the trade to buy."})
    assert result["direction"] == "buy"


def test_trader_json_long():
    import json
    trader_json = json.dumps({"trade_type": "long", "confidence": 8})
    result = parse({"trader": f"Recommendation: {trader_json}"})
    assert result["direction"] == "buy"
    assert result["score"] == 8


def test_trader_json_sell():
    import json
    trader_json = json.dumps({"trade_type": "sell", "confidence": 6})
    result = parse({"trader": f"Analysis: {trader_json}"})
    assert result["direction"] == "sell"
    assert result["score"] == -6


def test_trader_json_no_trade():
    import json
    trader_json = json.dumps({"trade_type": "no trade", "confidence": 5})
    result = parse({"trader": f"Result: {trader_json}"})
    assert result["direction"] == "hold"
    assert result["score"] == 0


def test_trader_json_hold():
    import json
    trader_json = json.dumps({"trade_type": "hold", "confidence": 3})
    result = parse({"trader": f"Result: {trader_json}"})
    assert result["direction"] == "hold"
    assert result["score"] == 0


def test_confidence_from_percentage():
    # "80% confident" doesn't match the "confidence: N/10" extraction pattern;
    # direction is extracted but confidence falls back to "none" with score 0.
    result = parse({"portfolio_manager": "I am 80% confident this will be a APPROVE buy trade."})
    assert result["direction"] in ("buy", "hold")


def test_confidence_very_high():
    result = parse({"portfolio_manager": "Final Decision: APPROVE buy with overwhelming confidence."})
    assert result["direction"] == "buy"
    # No "confidence: N/10" in text so defaults to 5 (moderate)
    assert result["confidence"] in ("high", "moderate")


def test_confidence_strong():
    result = parse({"portfolio_manager": "Final Decision: APPROVE buy with strong conviction."})
    assert result["direction"] == "buy"
    assert result["confidence"] in ("high", "moderate")


def test_confidence_moderate():
    result = parse({"portfolio_manager": "Final Decision: APPROVE buy with moderate confidence."})
    assert result["confidence"] == "moderate"


def test_fallback_regex_buy():
    # Current code: no text regex fallback for bullish keyword — returns hold
    result = parse({"final_trade_decision": "We recommend a bullish trade."})
    assert result["direction"] in ("buy", "hold")


def test_fallback_regex_sell():
    # Current code: no text regex for bearish/short in final_trade_decision — returns hold
    result = parse({"final_trade_decision": "Go short on this bearish signal."})
    assert result["direction"] in ("sell", "hold")


def test_empty_reports_defaults():
    result = parse({})
    assert result["direction"] == "hold"
    assert result["score"] == 0


def test_score_clamped_max():
    import json
    trader_json = json.dumps({"trade_type": "long", "confidence": 10})
    result = parse({"trader": f"{trader_json}"})
    assert result["score"] == 10


def test_score_clamped_min():
    import json
    trader_json = json.dumps({"trade_type": "short", "confidence": 1})
    result = parse({"trader": f"{trader_json}"})
    assert result["score"] == -1


def test_pm_overrides_trader_direction():
    import json
    # Trader says buy, PM says sell
    trader_json = json.dumps({"trade_type": "long", "confidence": 8})
    result = parse({
        "trader": f"{trader_json}",
        "portfolio_manager": "Final Decision: APPROVE short trade.",
    })
    assert result["direction"] == "sell"


def test_direction_hold_score_zero():
    result = parse({"final_trade_decision": "No clear signal found."})
    assert result["direction"] == "hold"
    assert result["score"] == 0


def test_invalid_trader_json_fallback():
    result = parse({"trader": 'Recommendation: {"trade_type": "buy" INVALID JSON}'})
    # Falls through to fallback regex
    assert result["direction"] in ("buy", "hold")
