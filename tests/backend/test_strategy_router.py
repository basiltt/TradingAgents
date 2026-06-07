"""Tests for pure strategy_router functions (route_strategy, resolve_final_side)."""

import itertools

import pytest

from backend.services.strategy_router import (
    route_strategy,
    resolve_final_side,
    feature_for,
    select_adaptive_blacklist,
)


# ── route_strategy (FR-004, FR-041, EC-05) ──

def test_route_trend_cohort_all_regimes():
    for regime in ("ranging", "trending", "volatile", "unknown"):
        assert route_strategy("trend", regime) == "trend"


def test_route_mr_cohort_ranging():
    assert route_strategy("mean_reversion", "ranging") == "mean_reversion"


@pytest.mark.parametrize("regime", ["trending", "volatile", "unknown"])
def test_route_mr_cohort_non_ranging_is_none(regime):
    assert route_strategy("mean_reversion", regime) == "none"


def test_route_unknown_cohort_defaults_trend():
    assert route_strategy("garbage", "ranging") == "trend"
    assert route_strategy("", "ranging") == "trend"


def test_route_custom_mr_regime():
    assert route_strategy("mean_reversion", "compression", mr_regime="compression") == "mean_reversion"
    assert route_strategy("mean_reversion", "ranging", mr_regime="compression") == "none"


# ── resolve_final_side exhaustive truth table (FR-005, R2-33, T-08) ──

def test_resolve_final_side_truth_table():
    # base: buy->long, sell->short. flip = reverse XOR mr_fade.
    expected = {
        # (signal_dir, reverse, mr_fade): side
        ("buy", False, False): "long",
        ("buy", True, False): "short",
        ("buy", False, True): "short",
        ("buy", True, True): "long",    # double-invert => identity
        ("sell", False, False): "short",
        ("sell", True, False): "long",
        ("sell", False, True): "long",
        ("sell", True, True): "short",  # double-invert => identity
    }
    for (sig, rev, fade), want in expected.items():
        assert resolve_final_side(sig, rev, fade) == want, f"{sig},{rev},{fade}"


def test_resolve_final_side_double_invert_is_identity():
    # explicit pin of the reverse ∧ fade => identity case
    for sig in ("buy", "sell"):
        assert resolve_final_side(sig, True, True) == resolve_final_side(sig, False, False)


def test_resolve_final_side_covers_full_domain():
    seen = set()
    for sig, rev, fade in itertools.product(("buy", "sell"), (True, False), (True, False)):
        seen.add(resolve_final_side(sig, rev, fade))
    assert seen == {"long", "short"}


# ── feature_for ──

def test_feature_for_cohort():
    assert feature_for("mean_reversion") == "f2"
    assert feature_for("trend") == "f1"
    assert feature_for("anything_else") == "f1"


# ── select_adaptive_blacklist (FR-030) ──

def test_select_adaptive_blacklist_picks_by_fade():
    cfg = {"_computed_adaptive_blacklist": ["T"], "_computed_mr_adaptive_blacklist": ["M"]}
    assert select_adaptive_blacklist(cfg, mr_fade=True) == ["M"]
    assert select_adaptive_blacklist(cfg, mr_fade=False) == ["T"]


def test_select_adaptive_blacklist_absent_keys_return_none():
    assert select_adaptive_blacklist({}, mr_fade=True) is None
    assert select_adaptive_blacklist({}, mr_fade=False) is None
