"""Tests for the new Regime Multi-Strategy AutoTradeConfig fields (TASK-0.3)."""

import pytest
from pydantic import ValidationError

from backend.schemas import AutoTradeConfig


def _cfg(**kw):
    return AutoTradeConfig(account_id="acc1", **kw)


def test_config_defaults_all_off():
    c = _cfg()
    assert c.regime_filter_enabled is False
    assert c.session_filter_enabled is False
    assert c.btc_vol_filter_enabled is False
    assert c.mean_reversion_enabled is False
    assert c.mr_long_enabled is False
    assert c.strategy_cohort == "trend"
    # conservative MR defaults
    assert c.mr_capital_pct == 2.0
    assert c.mr_leverage == 10
    assert c.mr_max_trades == 2
    assert c.mr_short_enabled is True


def test_session_blocklist_allowlist_mutual_exclusion():
    with pytest.raises(ValidationError):
        _cfg(session_blocked_hours_utc=[1, 6], session_allowed_hours_utc=[13, 14])
    # one alone is fine
    _cfg(session_blocked_hours_utc=[1, 6, 7, 8, 9, 10, 11, 12])
    _cfg(session_allowed_hours_utc=[13, 14, 15])


def test_session_hours_range_validated():
    with pytest.raises(ValidationError):
        _cfg(session_blocked_hours_utc=[24])
    with pytest.raises(ValidationError):
        _cfg(session_blocked_hours_utc=[-1])


def test_vol_min_lt_max():
    with pytest.raises(ValidationError):
        _cfg(btc_vol_min_threshold=2.0, btc_vol_max_threshold=1.0)
    _cfg(btc_vol_min_threshold=0.5, btc_vol_max_threshold=2.0)  # ok


def test_mr_requires_a_direction():
    with pytest.raises(ValidationError):
        _cfg(mean_reversion_enabled=True, mr_short_enabled=False, mr_long_enabled=False)
    _cfg(mean_reversion_enabled=True, mr_short_enabled=True, mr_long_enabled=False)  # ok


def test_old_config_without_new_fields_loads():
    # EC-12: a config dict lacking the new keys loads to default-off.
    c = AutoTradeConfig(account_id="legacy", leverage=20, capital_pct=5)
    assert c.regime_filter_enabled is False
    assert c.mean_reversion_enabled is False
    assert c.strategy_cohort == "trend"


def test_field_bounds_reject_out_of_range():
    with pytest.raises(ValidationError):
        _cfg(mr_leverage=200)
    with pytest.raises(ValidationError):
        _cfg(mr_capital_pct=0)
    with pytest.raises(ValidationError):
        _cfg(mr_time_stop_minutes=4)   # below 5 floor
    with pytest.raises(ValidationError):
        _cfg(mr_extreme_min_abs_score=11)


def test_strategy_cohort_enum():
    with pytest.raises(ValidationError):
        _cfg(strategy_cohort="both")   # v2-only, rejected in v1
    _cfg(strategy_cohort="mean_reversion")  # ok


def test_extra_keys_rejected_on_strict_ingress():
    # AutoTradeConfig keeps extra="forbid" for request ingress; old-code lenient
    # re-validation (AD7) is a separate model handled at the persistence boundary.
    with pytest.raises(ValidationError):
        AutoTradeConfig(account_id="x", totally_unknown_field=1)
