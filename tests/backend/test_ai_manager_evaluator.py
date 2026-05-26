"""Tests for AI Manager Evaluator — Phase 3 Task 3.4."""

import time
import pytest

from backend.services.ai_manager_evaluator import AIManagerEvaluator


@pytest.fixture
def evaluator():
    return AIManagerEvaluator()


class TestClassifyUrgency:
    def test_no_positions_returns_standard(self, evaluator):
        assert evaluator.classify_urgency([]) == "STANDARD"

    def test_no_indicators_returns_standard(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        assert evaluator.classify_urgency(positions) == "STANDARD"

    def test_pnl_velocity_triggers_fast(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"pnl_velocity_30s": 0.025}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"

    def test_pnl_velocity_at_boundary(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"pnl_velocity_30s": 0.02}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"

    def test_rsi_crosses_upper(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"rsi_14": 71.0, "prev_rsi_14": 69.0}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"

    def test_rsi_crosses_lower(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"rsi_14": 29.0, "prev_rsi_14": 31.0}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"

    def test_funding_rate_flip(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"funding_rate": -0.001, "prev_funding_rate": 0.001}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"

    def test_volatility_spike(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"candle_1m_body": 300.0, "atr_14": 100.0}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"

    def test_conflicting_signals_returns_deep(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"conflicting": True}}
        assert evaluator.classify_urgency(positions, indicators) == "DEEP"

    def test_symbol_cooldown_suppresses_second(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"pnl_velocity_30s": 0.05}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"
        # Second call within 15s should be suppressed
        assert evaluator.classify_urgency(positions, indicators) == "STANDARD"

    def test_negative_pnl_velocity_also_triggers(self, evaluator):
        positions = [{"symbol": "BTCUSDT"}]
        indicators = {"BTCUSDT": {"pnl_velocity_30s": -0.03}}
        assert evaluator.classify_urgency(positions, indicators) == "FAST"
