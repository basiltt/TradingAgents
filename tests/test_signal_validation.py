"""Tests for signal validation module (TASK-010)."""

from __future__ import annotations

import json
import pytest


class TestValidateSignal:
    def _validate(self, signal, **kwargs):
        from tradingagents.agents.utils.signal_validation import validate_signal
        return validate_signal(signal, **kwargs)

    def test_valid_long(self):
        sig = {
            "trade_type": "Long",
            "entry_price": 100.0,
            "stop_losses": [95.0, 90.0],
            "take_profits": [110.0, 120.0],
            "confidence": 7,
            "leverage": 5,
        }
        ok, errs = self._validate(sig)
        assert ok is True
        assert errs == []

    def test_valid_short(self):
        sig = {
            "trade_type": "Short",
            "entry_price": 100.0,
            "stop_losses": [105.0, 110.0],
            "take_profits": [90.0, 80.0],
            "confidence": 3,
            "leverage": 10,
        }
        ok, errs = self._validate(sig)
        assert ok is True

    def test_no_trade_with_nulls(self):
        sig = {
            "trade_type": "No Trade",
            "entry_price": None,
            "stop_losses": None,
            "take_profits": None,
            "confidence": 5,
            "leverage": 1,
        }
        ok, errs = self._validate(sig)
        assert ok is True

    def test_long_invalid_sl_above_entry(self):
        sig = {
            "trade_type": "Long",
            "entry_price": 100.0,
            "stop_losses": [105.0],
            "take_profits": [110.0],
            "confidence": 5,
            "leverage": 2,
        }
        ok, errs = self._validate(sig)
        assert ok is False
        assert any("stop" in e.lower() for e in errs)

    def test_short_invalid_tp_above_entry(self):
        sig = {
            "trade_type": "Short",
            "entry_price": 100.0,
            "stop_losses": [105.0],
            "take_profits": [110.0],  # TP above entry for short is invalid
            "confidence": 5,
            "leverage": 2,
        }
        ok, errs = self._validate(sig)
        assert ok is False

    def test_confidence_out_of_range(self):
        sig = {
            "trade_type": "Long",
            "entry_price": 100.0,
            "stop_losses": [95.0],
            "take_profits": [110.0],
            "confidence": 11,
            "leverage": 2,
        }
        ok, errs = self._validate(sig)
        assert ok is False
        assert any("confidence" in e.lower() for e in errs)

    def test_leverage_exceeds_max(self):
        sig = {
            "trade_type": "Long",
            "entry_price": 100.0,
            "stop_losses": [95.0],
            "take_profits": [110.0],
            "confidence": 5,
            "leverage": 25,
        }
        ok, errs = self._validate(sig, max_leverage=20)
        assert ok is False
        assert any("leverage" in e.lower() for e in errs)

    def test_confidence_zero_invalid(self):
        sig = {
            "trade_type": "Long",
            "entry_price": 100.0,
            "stop_losses": [95.0],
            "take_profits": [110.0],
            "confidence": 0,
            "leverage": 2,
        }
        ok, errs = self._validate(sig)
        assert ok is False


class TestParseSignalFromLLMOutput:
    def _parse(self, text):
        from tradingagents.agents.utils.signal_validation import parse_signal_from_llm_output
        return parse_signal_from_llm_output(text)

    def test_extracts_json_from_markdown_block(self):
        text = 'Here is my analysis:\n```json\n{"trade_type": "Long", "entry_price": 100}\n```\nDone.'
        result = self._parse(text)
        assert result["trade_type"] == "Long"
        assert result["entry_price"] == 100

    def test_extracts_bare_json(self):
        text = '{"trade_type": "Short", "entry_price": 50}'
        result = self._parse(text)
        assert result["trade_type"] == "Short"

    def test_returns_empty_on_no_json(self):
        text = "I recommend buying Bitcoin."
        result = self._parse(text)
        assert result == {}

    def test_extracts_largest_json_object(self):
        text = 'Small: {"a":1}\nBig: {"trade_type":"Long","entry_price":100,"stop_losses":[95],"take_profits":[110]}'
        result = self._parse(text)
        assert "trade_type" in result
