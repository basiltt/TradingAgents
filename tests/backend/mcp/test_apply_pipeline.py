"""Apply pipeline tests — TASK-P4-10 (AC-008/009/026, money path)."""
from __future__ import annotations

import pytest

from backend.mcp.tools.optimizer.apply import (
    SWEEPABLE_FIELDS,
    ApplyRejected,
    sanitize_patch,
    sanity_ceiling_ok,
    validate_merged_config,
)


def test_sweepable_fields_is_explicit_frozenset():
    assert isinstance(SWEEPABLE_FIELDS, frozenset)
    # safe tuning fields are present
    assert "leverage" in SWEEPABLE_FIELDS
    assert "take_profit_pct" in SWEEPABLE_FIELDS
    # live-enabling / dangerous fields are NOT sweepable
    assert "allow_real_trades" not in SWEEPABLE_FIELDS


def test_sanitize_strips_non_allowlisted_fields():
    patch = {"leverage": 10, "allow_real_trades": True, "auto_trade_enabled": True, "evil": "x"}
    clean = sanitize_patch(patch)
    assert clean == {"leverage": 10}  # only allow-listed survives
    assert "allow_real_trades" not in clean


def test_sanitize_rejects_when_only_dangerous_fields():
    # a patch that is ENTIRELY non-sweepable -> nothing to apply -> rejected
    with pytest.raises(ApplyRejected):
        sanitize_patch({"allow_real_trades": True}, reject_if_empty=True)


def test_sanity_ceiling_rejects_extreme_leverage():
    assert sanity_ceiling_ok({"leverage": 20, "stop_loss_pct": 100})
    assert not sanity_ceiling_ok({"leverage": 200, "stop_loss_pct": 100})  # > max


def test_sanity_ceiling_rejects_tiny_stop():
    assert not sanity_ceiling_ok({"leverage": 10, "stop_loss_pct": 0.1})  # below min stop distance


def test_validate_merged_config_runs_model_validators():
    # a patch that makes the MERGED config violate a cross-field model validator:
    # close_on_profit_pct requires target_goal_value (validate_target_goal).
    current = {
        "account_id": "acc1", "leverage": 10, "stop_loss_pct": 100.0,
        "take_profit_pct": 150.0, "capital_pct": 5.0, "direction": "straight",
    }
    bad_patch = {"close_on_profit_pct": 50.0}  # no target_goal_value -> invalid merged
    with pytest.raises(ApplyRejected):
        validate_merged_config(current, bad_patch)


def test_validate_merged_config_accepts_valid():
    current = {
        "account_id": "acc1", "leverage": 10, "stop_loss_pct": 100.0,
        "take_profit_pct": 150.0, "capital_pct": 5.0, "direction": "straight",
    }
    merged = validate_merged_config(current, {"take_profit_pct": 200.0})
    assert merged["take_profit_pct"] == 200.0
    assert merged["leverage"] == 10  # unchanged field preserved
