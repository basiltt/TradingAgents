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


def test_sanity_ceiling_bounds_mr_leverage_and_capital():
    """Regression (regime merge): the absolute non-overridable ceiling must also
    bound the mean-reversion leverage/capital fields, not just the trend ones.
    None (MR disabled) is allowed; over-bound values are a breach."""
    base = {"leverage": 20, "stop_loss_pct": 100, "capital_pct": 5}
    # MR fields absent / None → allowed (MR disabled)
    assert sanity_ceiling_ok(base)
    assert sanity_ceiling_ok({**base, "mr_leverage": None, "mr_capital_pct": None})
    # within bounds → allowed
    assert sanity_ceiling_ok({**base, "mr_leverage": 10, "mr_capital_pct": 2})
    # mr_leverage above the hard max → breach (schema allows up to 125; ceiling caps it)
    assert not sanity_ceiling_ok({**base, "mr_leverage": 125})
    # mr_capital_pct above the hard max → breach
    assert not sanity_ceiling_ok({**base, "mr_capital_pct": 80})


def test_regime_fields_are_not_sweepable():
    """Regression (regime merge): every Regime Multi-Strategy field is DENIED from
    optimizer sweeping (fail-closed) — the optimizer must never auto-tune MR/regime
    money knobs. Guards against a future accidental addition to SWEEPABLE_FIELDS."""
    regime_fields = {
        "mean_reversion_enabled", "mr_short_enabled", "mr_long_enabled",
        "mr_long_ack_requested", "strategy_cohort", "mr_regime", "mr_mean_interval",
        "mr_mean_period", "mr_capital_pct", "mr_leverage", "mr_max_trades",
        "mr_target_capture_pct", "mr_tight_stop_pct", "mr_time_stop_minutes",
        "mr_min_edge_pct", "mr_extreme_min_abs_score", "regime_filter_enabled",
        "regime_staleness_minutes", "regime_trend_ema_dist_pct", "regime_volatile_atr",
        "session_filter_enabled", "session_allowed_hours_utc", "session_blocked_hours_utc",
        "btc_vol_filter_enabled", "btc_vol_interval", "btc_vol_lookback_candles",
        "btc_vol_min_threshold", "btc_vol_max_threshold",
    }
    leaked = regime_fields & SWEEPABLE_FIELDS
    assert not leaked, f"regime fields must not be sweepable: {leaked}"


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
