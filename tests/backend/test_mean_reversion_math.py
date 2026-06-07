"""Tests for mean-reversion math: TP oracle + geometry guards (Phase 4 TASK-4.1/4.2)."""

import pytest

from backend.services.mean_reversion_math import (
    margin_tp_pct,
    mr_target_price,
    check_geometry,
)
from backend.services.strategy_reason_codes import ReasonCode


# ── TP conversion oracle (T-06): hand-computed exchange-correct values ──

def test_margin_tp_oracle_short_fade():
    # entry 102, mean 100 => distance_frac = 2/102 = 0.019607...
    # capture 60%, leverage 10:
    #   margin_tp% = 0.60 * 0.019607... * 10 * 100 = 11.7647...%
    val = margin_tp_pct(entry=102.0, mean=100.0, capture_pct=60.0, leverage=10.0)
    assert val == pytest.approx(0.60 * (2.0 / 102.0) * 10.0 * 100.0, rel=1e-9)
    assert val == pytest.approx(11.76470588, rel=1e-6)


def test_margin_tp_oracle_long_fade():
    # entry 98, mean 100 => distance 2/98, capture 50%, leverage 20
    val = margin_tp_pct(entry=98.0, mean=100.0, capture_pct=50.0, leverage=20.0)
    assert val == pytest.approx(0.50 * (2.0 / 98.0) * 20.0 * 100.0, rel=1e-9)


def test_margin_tp_clamped_to_distance_implied_max():
    # capture > 100 is nonsensical but must clamp to the full-distance value
    full = margin_tp_pct(entry=102.0, mean=100.0, capture_pct=100.0, leverage=10.0)
    over = margin_tp_pct(entry=102.0, mean=100.0, capture_pct=150.0, leverage=10.0)
    assert over == full  # clamped


def test_margin_tp_zero_entry_safe():
    assert margin_tp_pct(entry=0.0, mean=100.0, capture_pct=60.0, leverage=10.0) == 0.0


def test_mr_target_price_moves_toward_mean():
    # long fade: entry 98 below mean 100, 60% capture => 98 + (100-98)*.6 = 99.2
    assert mr_target_price(98.0, 100.0, 60.0, "long") == pytest.approx(99.2)
    # short fade: entry 102 above mean 100, 60% capture => 102 + (100-102)*.6 = 100.8
    assert mr_target_price(102.0, 100.0, 60.0, "short") == pytest.approx(100.8)


# ── geometry guards (FR-025) ──

def test_geometry_valid_short_fade():
    # entry above mean, tight SL small => valid
    assert check_geometry(102.0, 100.0, "short", tight_sl_pct=5.0, leverage=10.0,
                          min_edge_pct=1.0) is None


def test_geometry_valid_long_fade():
    assert check_geometry(98.0, 100.0, "long", tight_sl_pct=5.0, leverage=10.0,
                          min_edge_pct=1.0) is None


def test_geometry_no_edge():
    # entry 99.9, mean 100 => distance 0.1% < min_edge 1%
    assert check_geometry(99.9, 100.0, "long", tight_sl_pct=5.0, leverage=10.0,
                          min_edge_pct=1.0) == ReasonCode.MR_NO_EDGE


def test_geometry_degenerate_long_tp_below_entry():
    # "long" but entry ABOVE mean => TP would be below entry => degenerate
    assert check_geometry(102.0, 100.0, "long", tight_sl_pct=5.0, leverage=10.0,
                          min_edge_pct=1.0) == ReasonCode.MR_DEGENERATE_TARGET


def test_geometry_degenerate_short_tp_above_entry():
    assert check_geometry(98.0, 100.0, "short", tight_sl_pct=5.0, leverage=10.0,
                          min_edge_pct=1.0) == ReasonCode.MR_DEGENERATE_TARGET


def test_geometry_fee_floor():
    # Need TP margin between the no-edge floor and the fee floor.
    # entry 100.1, mean 100, leverage 1: distance = 0.1/100.1 = 0.0999% -> tp_margin 0.0999%.
    # fee_margin = 0.0015 * 1 * 100 = 0.15%. tp (0.0999) <= fee (0.15) => FEE_FLOOR.
    # min_edge 0.05 < 0.0999 so the no-edge guard passes first.
    rc = check_geometry(100.1, 100.0, "short", tight_sl_pct=0.001, leverage=1.0,
                        min_edge_pct=0.05, round_trip_fee_frac=0.0015)
    assert rc == ReasonCode.MR_FEE_FLOOR


def test_geometry_inverted_when_sl_wider_than_tp():
    # valid distance/fee, but tight_sl_pct >= tp_margin => inverted
    # entry 102 mean 100 leverage 10 => tp_margin ~19.6% (full). SL 25% > TP.
    rc = check_geometry(102.0, 100.0, "short", tight_sl_pct=25.0, leverage=10.0,
                        min_edge_pct=1.0)
    assert rc == ReasonCode.MR_INVERTED_GEOMETRY


def test_geometry_zero_prices_degenerate():
    assert check_geometry(0.0, 100.0, "long", tight_sl_pct=5.0, leverage=10.0,
                          min_edge_pct=1.0) == ReasonCode.MR_DEGENERATE_TARGET
