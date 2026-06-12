"""Tests for the 8 Cool Off Time config fields on AutoTradeConfig + BacktestCreateRequest.

Cool Off Time feature: TASK-P1-2 / P1-3. Covers FR-001/002, CO-CFG-1..5: field presence,
defaults OFF, bounds (1..43200), enabled-requires-minutes validator, extra=forbid,
absent-fields-default-OFF, and the identical mirror on the backtest request.
"""

import pytest
from pydantic import ValidationError

from backend.schemas import AutoTradeConfig

COOLOFF_FIELDS = [
    "cooloff_on_success_enabled", "cooloff_on_success_minutes",
    "cooloff_on_failure_enabled", "cooloff_on_failure_minutes",
    "cooloff_on_double_success_enabled", "cooloff_on_double_success_minutes",
    "cooloff_on_double_failure_enabled", "cooloff_on_double_failure_minutes",
]


def _base_auto(**kw):
    base = dict(account_id="acc-1")
    base.update(kw)
    return base


# ── AutoTradeConfig ──────────────────────────────────────────────────────────

def test_autotrade_defaults_all_off():
    c = AutoTradeConfig(**_base_auto())
    assert c.cooloff_on_success_enabled is False
    assert c.cooloff_on_success_minutes is None
    assert c.cooloff_on_failure_enabled is False
    assert c.cooloff_on_failure_minutes is None
    assert c.cooloff_on_double_success_enabled is False
    assert c.cooloff_on_double_success_minutes is None
    assert c.cooloff_on_double_failure_enabled is False
    assert c.cooloff_on_double_failure_minutes is None


def test_autotrade_absent_fields_default_off():
    # A config dict with NONE of the cooloff keys (legacy scan_config blob) must parse.
    c = AutoTradeConfig.model_validate(_base_auto())
    assert not any(getattr(c, f) for f in COOLOFF_FIELDS if f.endswith("_enabled"))


def test_autotrade_enabled_with_minutes_ok():
    c = AutoTradeConfig(**_base_auto(
        cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=60))
    assert c.cooloff_on_failure_enabled is True
    assert c.cooloff_on_failure_minutes == 60


@pytest.mark.parametrize("minutes", [1, 43200])
def test_autotrade_minutes_bounds_accept(minutes):
    c = AutoTradeConfig(**_base_auto(
        cooloff_on_success_enabled=True, cooloff_on_success_minutes=minutes))
    assert c.cooloff_on_success_minutes == minutes


@pytest.mark.parametrize("minutes", [0, -1, 43201])
def test_autotrade_minutes_bounds_reject(minutes):
    with pytest.raises(ValidationError):
        AutoTradeConfig(**_base_auto(
            cooloff_on_success_enabled=True, cooloff_on_success_minutes=minutes))


def test_autotrade_enabled_without_minutes_rejected():
    for tier in ("success", "failure", "double_success", "double_failure"):
        with pytest.raises(ValidationError):
            AutoTradeConfig(**_base_auto(**{f"cooloff_on_{tier}_enabled": True}))


def test_autotrade_disabled_with_minutes_ok():
    # a disabled tier accepts (and ignores) a real minutes value — validator must NOT reject
    c = AutoTradeConfig(**_base_auto(
        cooloff_on_success_enabled=False, cooloff_on_success_minutes=60))
    assert c.cooloff_on_success_enabled is False
    assert c.cooloff_on_success_minutes == 60


def test_autotrade_all_four_tiers_enabled_ok():
    c = AutoTradeConfig(**_base_auto(
        cooloff_on_success_enabled=True, cooloff_on_success_minutes=30,
        cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=60,
        cooloff_on_double_success_enabled=True, cooloff_on_double_success_minutes=60,
        cooloff_on_double_failure_enabled=True, cooloff_on_double_failure_minutes=120,
    ))
    assert c.cooloff_on_double_failure_minutes == 120


def test_autotrade_extra_field_forbidden():
    with pytest.raises(ValidationError):
        AutoTradeConfig(**_base_auto(cooloff_on_sucess_enabled=True))  # typo'd key


# ── BacktestCreateRequest (mirror) ───────────────────────────────────────────

def _base_bt(**kw):
    from datetime import datetime, timezone
    base = dict(
        starting_capital=1000.0,
        date_range_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        date_range_end=datetime(2024, 1, 10, tzinfo=timezone.utc),
        scan_source={"mode": "date_range"},
    )
    base.update(kw)
    return base


def test_backtest_defaults_all_off():
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    r = BacktestCreateRequest(**_base_bt())
    for f in COOLOFF_FIELDS:
        if f.endswith("_enabled"):
            assert getattr(r, f) is False, f
        else:
            assert getattr(r, f) is None, f


def test_backtest_enabled_without_minutes_rejected_all_tiers():
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    for tier in ("success", "failure", "double_success", "double_failure"):
        with pytest.raises(ValidationError):
            BacktestCreateRequest(**_base_bt(**{f"cooloff_on_{tier}_enabled": True}))


@pytest.mark.parametrize("minutes", [1, 43200])
def test_backtest_minutes_bounds_accept(minutes):
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    r = BacktestCreateRequest(**_base_bt(
        cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=minutes))
    assert r.cooloff_on_failure_minutes == minutes


@pytest.mark.parametrize("minutes", [0, -1, 43201])
def test_backtest_minutes_bounds_reject(minutes):
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    with pytest.raises(ValidationError):
        BacktestCreateRequest(**_base_bt(
            cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=minutes))


def test_backtest_all_four_tiers_enabled_ok():
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    r = BacktestCreateRequest(**_base_bt(
        cooloff_on_success_enabled=True, cooloff_on_success_minutes=30,
        cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=60,
        cooloff_on_double_success_enabled=True, cooloff_on_double_success_minutes=60,
        cooloff_on_double_failure_enabled=True, cooloff_on_double_failure_minutes=120,
    ))
    assert r.cooloff_on_double_failure_minutes == 120


def test_backtest_extra_field_forbidden():
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    with pytest.raises(ValidationError):
        BacktestCreateRequest(**_base_bt(cooloff_on_sucess_enabled=True))  # typo'd key


def test_backtest_enabled_with_minutes_ok():
    from backend.schemas.backtest_schemas import BacktestCreateRequest
    r = BacktestCreateRequest(**_base_bt(
        cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=60))
    assert r.cooloff_on_failure_minutes == 60
