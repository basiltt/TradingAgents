"""Tests for the ReasonCode enum (TASK-0.2).

The load-bearing invariant: each enum value equals its legacy string literal, so
migrating _emit_decision call sites to the enum cannot change trace output (the
all-off golden snapshot, FR-001, depends on this).
"""

from backend.services.strategy_reason_codes import ReasonCode


def test_reason_code_values_match_legacy_strings():
    # These are the literals previously passed to _emit_decision in auto_trade_service.
    legacy = {
        "blacklist", "whitelist", "already_held", "max_signal_age", "hold_signal",
        "max_same_direction", "max_same_sector", "adaptive_blacklist", "signal_sides",
        "min_score", "confidence_filter", "max_trades", "target_goal_reached",
        "price_drift", "no_balance",
    }
    enum_values = {rc.value for rc in ReasonCode}
    # Every legacy literal must be representable by the enum with identical value.
    missing = legacy - enum_values
    assert not missing, f"legacy reason strings absent from ReasonCode: {missing}"


def test_reason_code_is_str_subclass():
    # str subclass => passes transparently where a str reason_code is expected.
    assert isinstance(ReasonCode.MIN_SCORE, str)
    assert ReasonCode.MIN_SCORE == "min_score"
    assert f"{ReasonCode.MIN_SCORE}" == "min_score"
    assert ReasonCode.MIN_SCORE.value == "min_score"


def test_new_reason_codes_present():
    for name in (
        "SESSION_FILTER", "BTC_VOL_FILTER", "VOL_UNAVAILABLE", "COHORT_MISMATCH",
        "MR_REGIME_EXCLUDED", "MR_LONG_DISABLED", "MR_LONG_UNACKNOWLEDGED",
        "MR_NO_EDGE", "MR_DEGENERATE_TARGET", "MR_MEAN_UNAVAILABLE",
        "MR_INSUFFICIENT_HISTORY", "MR_FEE_FLOOR", "MR_SL_LIQUIDATION",
        "MR_INVERTED_GEOMETRY", "MR_REGIME_STALE", "MR_PRICE_UNAVAILABLE",
        "FEATURE_KILLED",
    ):
        assert hasattr(ReasonCode, name), f"missing new reason code {name}"


def test_reason_code_values_unique():
    values = [rc.value for rc in ReasonCode]
    assert len(values) == len(set(values)), "duplicate ReasonCode values"
