"""Tests for the centralized feature registry + F3 cohort resolution (FR-040)."""

from __future__ import annotations

from backend.services import features as feat


# ── feature registry ──

def test_kill_switch_features_set():
    assert feat.KILL_SWITCH_FEATURES == frozenset({"__all__", "f1", "f2", "f2_long"})


def test_feature_for_cohort():
    assert feat.feature_for_cohort("mean_reversion") == "f2"
    assert feat.feature_for_cohort("trend") == "f1"
    assert feat.feature_for_cohort("anything") == "f1"


def test_strategy_router_delegates_to_registry():
    # strategy_router.feature_for must stay in sync with the registry (no drift).
    from backend.services.strategy_router import feature_for
    assert feature_for("mean_reversion") == feat.feature_for_cohort("mean_reversion")
    assert feature_for("trend") == feat.feature_for_cohort("trend")


# ── resolve_cohort precedence (per-scan override > stored > default) ──

def test_stored_cohort_drives_routing_when_scan_is_default():
    # The fleet-roster bug: account stored as mean_reversion, scan cfg left at default.
    assert feat.resolve_cohort("trend", "mean_reversion") == "mean_reversion"


def test_scan_explicit_mr_overrides_stored_trend():
    assert feat.resolve_cohort("mean_reversion", "trend") == "mean_reversion"


def test_both_trend_resolves_trend():
    assert feat.resolve_cohort("trend", "trend") == "trend"


def test_no_stored_falls_back_to_scan_or_default():
    assert feat.resolve_cohort("mean_reversion", None) == "mean_reversion"
    assert feat.resolve_cohort("trend", None) == "trend"
    assert feat.resolve_cohort(None, None) == "trend"


def test_none_scan_uses_stored():
    assert feat.resolve_cohort(None, "mean_reversion") == "mean_reversion"


def test_invalid_values_ignored():
    assert feat.resolve_cohort("bogus", "mean_reversion") == "mean_reversion"  # bad scan -> stored
    assert feat.resolve_cohort("trend", "bogus") == "trend"                    # bad stored -> default
