"""Tests for cooloff_core — the pure decision engine for Cool Off Time.

Cool Off Time feature: TASK-P1-1. Pure module, no I/O. Covers FR-005/006/007 (decision part),
the streak state machine (CO-STREAK-2..7), double-overrides-single (CO-CORE-4/6), clamp, and
classify_outcome edge cases.
"""

import math

import dataclasses
import pytest

from backend.services.cooloff_core import (
    STALE_MIN_MINUTES,
    CLAMP_MAX_DAYS,
    DOUBLE_THRESHOLD,
    STREAK_CLAMP,
    COOLOFF_MIN_MINUTES,
    COOLOFF_MAX_MINUTES,
    ArmDecision,
    CooloffSettings,
    StreakState,
    any_tier_enabled,
    classify_outcome,
    decide,
    settings_from_config,
    settings_to_columns,
)


# ── module constants (CR-6) ─────────────────────────────────────────────────

def test_module_constants():
    assert STALE_MIN_MINUTES == 1560
    assert CLAMP_MAX_DAYS == 31
    assert DOUBLE_THRESHOLD == 2
    assert STREAK_CLAMP == 2
    assert COOLOFF_MIN_MINUTES == 1
    assert COOLOFF_MAX_MINUTES == 43200


# ── shared mappers (config <-> settings <-> columns) ────────────────────────

def test_settings_from_config_roundtrip_and_defaults():
    cfg = {
        "cooloff_on_success_enabled": True, "cooloff_on_success_minutes": 30,
        "cooloff_on_double_failure_enabled": True, "cooloff_on_double_failure_minutes": 120,
        # failure + double_success omitted entirely -> default off/None
    }
    s = settings_from_config(cfg)
    assert (s.success_enabled, s.success_minutes) == (True, 30)
    assert (s.failure_enabled, s.failure_minutes) == (False, None)
    assert (s.double_success_enabled, s.double_success_minutes) == (False, None)
    assert (s.double_failure_enabled, s.double_failure_minutes) == (True, 120)
    cols = settings_to_columns(s)
    assert cols["success_minutes"] == 30 and cols["double_failure_minutes"] == 120
    assert cols["failure_enabled"] is False and cols["failure_minutes"] is None


def test_setting_cols_and_keys_agree_with_mapper():
    """The repository's _SETTING_COLS, the classifier's _SETTING_KEYS, and the shared
    settings_to_columns output must all carry the SAME 8 column names — a single point
    of drift if a tier is ever added/renamed."""
    from backend.services.cooloff_repository import _SETTING_COLS
    from backend.services.cooloff_classifier import _SETTING_KEYS
    mapper_keys = set(settings_to_columns(settings_from_config({})).keys())
    assert set(_SETTING_COLS) == mapper_keys
    assert set(_SETTING_KEYS) == mapper_keys
    assert tuple(_SETTING_COLS) == tuple(_SETTING_KEYS)  # same order too


# ── classify_outcome (FR-005) ───────────────────────────────────────────────

@pytest.mark.parametrize("net,expected", [
    (10.0, "success"),
    (0.0001, "success"),
    (-10.0, "failure"),
    (-0.0001, "failure"),
    (0.0, "neutral"),
    (-0.0, "neutral"),
    (None, "neutral"),
    (float("nan"), "neutral"),
    (float("inf"), "neutral"),
    (float("-inf"), "neutral"),
])
def test_classify_outcome(net, expected):
    assert classify_outcome(net) == expected


# ── settings helpers ────────────────────────────────────────────────────────

def _settings(**kw) -> CooloffSettings:
    base = dict(
        success_enabled=False, success_minutes=None,
        failure_enabled=False, failure_minutes=None,
        double_success_enabled=False, double_success_minutes=None,
        double_failure_enabled=False, double_failure_minutes=None,
    )
    base.update(kw)
    return CooloffSettings(**base)


def test_any_tier_enabled():
    assert not any_tier_enabled(_settings())
    assert any_tier_enabled(_settings(success_enabled=True, success_minutes=30))
    assert any_tier_enabled(_settings(double_failure_enabled=True, double_failure_minutes=120))


# ── decide: neutral is transparent (CO-STREAK-3) ────────────────────────────

def test_neutral_transparent_no_arm_no_streak_change():
    st = StreakState(consecutive_wins=1, consecutive_losses=0)
    d = decide(st, "neutral", _settings(success_enabled=True, success_minutes=30))
    assert d.arm is False
    assert d.reason is None
    assert d.duration_minutes is None
    assert d.streaks == st  # unchanged


# ── decide: first cycle (0 -> 1) ────────────────────────────────────────────

def test_first_success_single_arms_and_streak_one():
    d = decide(StreakState(0, 0), "success", _settings(success_enabled=True, success_minutes=30))
    assert d.arm is True
    assert d.reason == "success"
    assert d.duration_minutes == 30
    assert d.streaks == StreakState(1, 0)


def test_first_failure_single_arms_and_streak_one():
    d = decide(StreakState(0, 0), "failure", _settings(failure_enabled=True, failure_minutes=60))
    assert d.arm is True
    assert d.reason == "failure"
    assert d.duration_minutes == 60
    assert d.streaks == StreakState(0, 1)


# ── decide: opposite outcome resets the other side (CO-STREAK-2) ────────────

def test_failure_resets_win_streak_to_zero_and_loss_to_one():
    d = decide(StreakState(2, 0), "failure", _settings(failure_enabled=True, failure_minutes=60))
    assert d.streaks == StreakState(0, 1)
    assert d.reason == "failure"


def test_success_resets_loss_streak_to_zero_and_win_to_one():
    d = decide(StreakState(0, 2), "success", _settings(success_enabled=True, success_minutes=30))
    assert d.streaks == StreakState(1, 0)
    assert d.reason == "success"


# ── decide: double fires at exactly 2, then resets that side to 0 (CO-STREAK-5) ──

def test_second_consecutive_success_fires_double_and_resets():
    d = decide(StreakState(1, 0), "success",
               _settings(double_success_enabled=True, double_success_minutes=90))
    assert d.arm is True
    assert d.reason == "double_success"
    assert d.duration_minutes == 90
    assert d.streaks == StreakState(0, 0)  # reset after double fires


def test_second_consecutive_failure_fires_double_and_resets():
    d = decide(StreakState(0, 1), "failure",
               _settings(double_failure_enabled=True, double_failure_minutes=120))
    assert d.arm is True
    assert d.reason == "double_failure"
    assert d.duration_minutes == 120
    assert d.streaks == StreakState(0, 0)


# ── decide: double OVERRIDES single when both enabled (CO-CORE-6) ────────────

def test_double_overrides_single_both_enabled_success():
    d = decide(StreakState(1, 0), "success", _settings(
        success_enabled=True, success_minutes=30,
        double_success_enabled=True, double_success_minutes=90,
    ))
    assert d.reason == "double_success"
    assert d.duration_minutes == 90  # not 30, not 120


def test_double_overrides_single_both_enabled_failure():
    d = decide(StreakState(0, 1), "failure", _settings(
        failure_enabled=True, failure_minutes=60,
        double_failure_enabled=True, double_failure_minutes=120,
    ))
    assert d.reason == "double_failure"
    assert d.duration_minutes == 120


# ── decide: first of two with both enabled arms SINGLE (CO-STREAK / AC transition) ──

def test_first_success_with_both_enabled_arms_single():
    d = decide(StreakState(0, 0), "success", _settings(
        success_enabled=True, success_minutes=30,
        double_success_enabled=True, double_success_minutes=90,
    ))
    assert d.reason == "success"
    assert d.duration_minutes == 30
    assert d.streaks == StreakState(1, 0)


# ── decide: single-only at clamp keeps arming single every time (CO-STREAK-7) ──

def test_single_only_at_clamp_keeps_arming_single():
    # wins already clamped at 2, double DISABLED, single enabled -> arms single, stays clamped
    d = decide(StreakState(2, 0), "success", _settings(success_enabled=True, success_minutes=30))
    assert d.arm is True
    assert d.reason == "success"
    assert d.streaks == StreakState(2, 0)  # clamp holds


def test_streak_clamp_never_exceeds_two_success():
    d = decide(StreakState(2, 0), "success", _settings())  # no tier enabled
    assert d.streaks == StreakState(2, 0)
    assert d.arm is False


def test_streak_clamp_never_exceeds_two_failure():
    d = decide(StreakState(0, 2), "failure", _settings())
    assert d.streaks == StreakState(0, 2)
    assert d.arm is False


# ── decide: tier not enabled -> no arm but streak still advances (CO-STREAK-7) ──

def test_success_no_tier_enabled_advances_streak_no_arm():
    d = decide(StreakState(0, 0), "success", _settings())
    assert d.arm is False
    assert d.reason is None
    assert d.streaks == StreakState(1, 0)


# ── decide: double enabled but only at streak 1 -> first arms nothing if single off ──

def test_first_failure_only_double_enabled_no_arm_streak_one():
    d = decide(StreakState(0, 0), "failure",
               _settings(double_failure_enabled=True, double_failure_minutes=120))
    assert d.arm is False  # streak only 1, double needs 2
    assert d.streaks == StreakState(0, 1)


# ── decide: defensive — arm with None minutes must NOT arm (defensive guard) ──

def test_defensive_enabled_but_none_minutes_does_not_arm():
    # schema normally rejects this, but decide() must be defensive
    d = decide(StreakState(0, 0), "success", _settings(success_enabled=True, success_minutes=None))
    assert d.arm is False
    assert d.duration_minutes is None


def test_defensive_double_enabled_none_minutes_does_not_arm():
    d = decide(StreakState(0, 1), "failure",
               _settings(double_failure_enabled=True, double_failure_minutes=None))
    assert d.arm is False


# ── ArmDecision / dataclasses are frozen ─────────────────────────────────────

def test_dataclasses_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        StreakState(0, 0).consecutive_wins = 5  # type: ignore
    with pytest.raises(dataclasses.FrozenInstanceError):
        _settings().success_enabled = True  # type: ignore
    with pytest.raises(dataclasses.FrozenInstanceError):
        ArmDecision(StreakState(0, 0), False, None, None).arm = True  # type: ignore


# ── classify_outcome defensive branch (non-numeric -> neutral, P1Q-F5) ───────

def test_classify_outcome_non_numeric_neutral():
    assert classify_outcome(complex(1, 2)) == "neutral"  # type: ignore[arg-type]

    class _Weird:
        def __gt__(self, other):  # pragma: no cover - defensive
            raise TypeError("nope")
    assert classify_outcome(_Weird()) == "neutral"  # type: ignore[arg-type]


def test_any_tier_enabled_each_term():
    assert any_tier_enabled(_settings(success_enabled=True, success_minutes=30))
    assert any_tier_enabled(_settings(failure_enabled=True, failure_minutes=60))
    assert any_tier_enabled(_settings(double_success_enabled=True, double_success_minutes=60))
    assert any_tier_enabled(_settings(double_failure_enabled=True, double_failure_minutes=120))


# ── FAILURE-SIDE SYMMETRY MIRRORS (P1R-F3 / P1Q-F1/F7/F8) ────────────────────

def test_first_failure_with_both_enabled_arms_single():
    d = decide(StreakState(0, 0), "failure", _settings(
        failure_enabled=True, failure_minutes=60,
        double_failure_enabled=True, double_failure_minutes=120,
    ))
    assert d.reason == "failure"
    assert d.duration_minutes == 60
    assert d.streaks == StreakState(0, 1)


def test_single_only_at_clamp_keeps_arming_single_failure():
    d = decide(StreakState(0, 2), "failure", _settings(failure_enabled=True, failure_minutes=60))
    assert d.arm is True
    assert d.reason == "failure"
    assert d.streaks == StreakState(0, 2)  # clamp holds


def test_failure_no_tier_enabled_advances_streak_no_arm():
    d = decide(StreakState(0, 0), "failure", _settings())
    assert d.arm is False
    assert d.reason is None
    assert d.streaks == StreakState(0, 1)


def test_first_success_only_double_enabled_no_arm_streak_one():
    d = decide(StreakState(0, 0), "success",
               _settings(double_success_enabled=True, double_success_minutes=90))
    assert d.arm is False  # streak only 1, double needs 2
    assert d.streaks == StreakState(1, 0)


# ── defensive None-minutes fall-through to single (P1R-F2) ───────────────────

def test_defensive_double_success_none_minutes_falls_through_to_single():
    # double enabled but minutes None -> must fall through and arm the valid single tier
    d = decide(StreakState(1, 0), "success", _settings(
        success_enabled=True, success_minutes=30,
        double_success_enabled=True, double_success_minutes=None,
    ))
    assert d.arm is True
    assert d.reason == "success"
    assert d.duration_minutes == 30


def test_defensive_double_failure_none_minutes_falls_through_to_single():
    d = decide(StreakState(0, 1), "failure", _settings(
        failure_enabled=True, failure_minutes=60,
        double_failure_enabled=True, double_failure_minutes=None,
    ))
    assert d.arm is True
    assert d.reason == "failure"
    assert d.duration_minutes == 60


def test_defensive_failure_single_none_minutes_no_arm():
    d = decide(StreakState(0, 0), "failure", _settings(failure_enabled=True, failure_minutes=None))
    assert d.arm is False
    assert d.duration_minutes is None


def test_defensive_double_success_none_minutes_only_double_no_arm():
    d = decide(StreakState(1, 0), "success",
               _settings(double_success_enabled=True, double_success_minutes=None))
    assert d.arm is False

