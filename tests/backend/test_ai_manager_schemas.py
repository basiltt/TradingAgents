"""Tests for AI Manager Pydantic schemas — Phase 1 Task 1.2."""

import pytest
from decimal import Decimal


def test_ai_manager_config_defaults():
    from backend.ai_manager_schemas import AIManagerConfig

    cfg = AIManagerConfig()
    assert cfg.enabled is False
    assert cfg.risk_tolerance == "moderate"
    assert cfg.evaluation_interval_s == 60
    assert cfg.max_daily_actions == 30
    assert cfg.max_hourly_actions == 10
    assert cfg.max_daily_loss_pct == 5.0
    assert cfg.confidence_threshold == 0.7
    assert cfg.max_single_decision_loss_pct == 3.0
    assert cfg.dry_run is False
    assert cfg.grace_period_s == 0
    assert cfg.excluded_symbols == []
    assert cfg.locked_positions == []
    assert cfg.strategy_version == "default"


def test_ai_manager_config_bounds():
    from backend.ai_manager_schemas import AIManagerConfig

    with pytest.raises(Exception):
        AIManagerConfig(evaluation_interval_s=29)
    with pytest.raises(Exception):
        AIManagerConfig(evaluation_interval_s=301)
    with pytest.raises(Exception):
        AIManagerConfig(max_daily_actions=4)
    with pytest.raises(Exception):
        AIManagerConfig(max_daily_actions=101)
    with pytest.raises(Exception):
        AIManagerConfig(max_daily_loss_pct=0.5)
    with pytest.raises(Exception):
        AIManagerConfig(max_daily_loss_pct=25.1)
    with pytest.raises(Exception):
        AIManagerConfig(confidence_threshold=0.29)
    with pytest.raises(Exception):
        AIManagerConfig(confidence_threshold=0.96)


def test_ai_manager_config_valid_symbols():
    from backend.ai_manager_schemas import AIManagerConfig

    cfg = AIManagerConfig(excluded_symbols=["BTCUSDT", "ETHUSDT"])
    assert cfg.excluded_symbols == ["BTCUSDT", "ETHUSDT"]


def test_ai_manager_config_invalid_symbol_pattern():
    from backend.ai_manager_schemas import AIManagerConfig

    with pytest.raises(Exception):
        AIManagerConfig(excluded_symbols=["btc-usdt"])


def test_ai_manager_config_symbols_max_length():
    from backend.ai_manager_schemas import AIManagerConfig

    with pytest.raises(Exception):
        AIManagerConfig(excluded_symbols=["A"] * 51)


def test_position_action_valid():
    from backend.ai_manager_schemas import PositionAction

    pa = PositionAction(symbol="BTCUSDT", action="close")
    assert pa.symbol == "BTCUSDT"
    assert pa.action == "close"
    assert pa.close_pct is None


def test_position_action_partial_close():
    from backend.ai_manager_schemas import PositionAction

    pa = PositionAction(symbol="ETHUSDT", action="partial_close", close_pct=50)
    assert pa.close_pct == 50


def test_position_action_invalid_close_pct():
    from backend.ai_manager_schemas import PositionAction

    with pytest.raises(Exception):
        PositionAction(symbol="BTCUSDT", action="partial_close", close_pct=0)
    with pytest.raises(Exception):
        PositionAction(symbol="BTCUSDT", action="partial_close", close_pct=101)


def test_position_action_invalid_symbol():
    from backend.ai_manager_schemas import PositionAction

    with pytest.raises(Exception):
        PositionAction(symbol="btc-usdt", action="hold")


def test_ai_manager_action_valid():
    from backend.ai_manager_schemas import AIManagerAction, PositionAction

    action = AIManagerAction(
        action_type="FULL_CLOSE",
        positions=[PositionAction(symbol="BTCUSDT", action="close")],
        confidence=0.85,
        reasoning="Trend reversal detected",
        urgency="high",
    )
    assert action.action_type == "FULL_CLOSE"
    assert action.confidence == 0.85


def test_ai_manager_action_invalid_confidence():
    from backend.ai_manager_schemas import AIManagerAction, PositionAction

    with pytest.raises(Exception):
        AIManagerAction(
            action_type="HOLD",
            positions=[],
            confidence=1.1,
            reasoning="test",
            urgency="low",
        )


def test_ai_manager_action_reasoning_max_length():
    from backend.ai_manager_schemas import AIManagerAction, PositionAction

    with pytest.raises(Exception):
        AIManagerAction(
            action_type="HOLD",
            positions=[],
            confidence=0.5,
            reasoning="x" * 501,
            urgency="low",
        )


def test_ai_manager_config_patch_semantics():
    from backend.ai_manager_schemas import AIManagerConfigPatch

    patch = AIManagerConfigPatch(risk_tolerance="aggressive")
    assert "risk_tolerance" in patch.model_fields_set
    assert "max_daily_actions" not in patch.model_fields_set


def test_ai_manager_config_patch_bounds():
    from backend.ai_manager_schemas import AIManagerConfigPatch

    with pytest.raises(Exception):
        AIManagerConfigPatch(evaluation_interval_s=29)
    with pytest.raises(Exception):
        AIManagerConfigPatch(max_daily_actions=0)


def test_ai_manager_status_model():
    from backend.ai_manager_schemas import AIManagerStatus
    from datetime import datetime

    status = AIManagerStatus(
        enabled=True,
        state="monitoring",
        last_analysis_at=datetime(2026, 1, 1),
        circuit_breaker={"count": 0, "active": False},
        actions_today=5,
        budget_remaining={"actions": 25, "tokens": 90000},
        degradation_tier=0,
        kill_switch=False,
    )
    assert status.enabled is True
    assert status.state == "monitoring"


def test_ai_manager_decision_response():
    from backend.ai_manager_schemas import AIManagerDecisionResponse
    from datetime import datetime

    resp = AIManagerDecisionResponse(
        id=1,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        action_taken={"action_type": "HOLD", "positions": []},
        reasoning="Market stable",
        confidence=0.6,
        urgency="low",
        execution_result=None,
        outcome=None,
        outcome_label=None,
    )
    assert resp.id == 1
    assert resp.confidence == 0.6
