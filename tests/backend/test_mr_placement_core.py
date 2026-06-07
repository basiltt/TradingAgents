"""Tests for the pure MR-placement core shared by live executor + backtester (Phase 3).

compute_mr_placement factors the side/direction/geometry/TP logic out of the live
async _compute_mr_params so the backtester can replay it identically (no drift). The
oracle assertions pin it against the same mean_reversion_math primitives the live
path uses.
"""

from __future__ import annotations

from backend.services import mean_reversion_math as mr
from backend.services.strategy_reason_codes import ReasonCode


def _cfg(**kw):
    base = {"mr_leverage": 10, "mr_capital_pct": 2.0, "mr_target_capture_pct": 60.0,
            "mr_tight_stop_pct": 6.0, "mr_min_edge_pct": 1.0,
            "mr_short_enabled": True, "mr_long_enabled": False}
    base.update(kw)
    return base


def test_fade_short_when_entry_above_mean():
    # entry 102 >= mean 100 -> fade SHORT (price reverts down).
    out = mr.compute_mr_placement(entry=102.0, mean=100.0, cfg=_cfg())
    assert not isinstance(out, ReasonCode)
    assert out["signal_direction"] == "short"
    assert out["leverage"] == 10
    assert out["capital_pct"] == 2.0
    # TP equals the oracle margin_tp_pct for these inputs
    assert out["take_profit_pct"] == mr.margin_tp_pct(102.0, 100.0, 60.0, 10.0)
    assert out["stop_loss_pct"] == 6.0


def test_fade_long_when_entry_below_mean():
    out = mr.compute_mr_placement(entry=98.0, mean=100.0, cfg=_cfg(mr_long_enabled=True))
    assert not isinstance(out, ReasonCode)
    assert out["signal_direction"] == "long"


def test_short_disabled_skips():
    out = mr.compute_mr_placement(entry=102.0, mean=100.0, cfg=_cfg(mr_short_enabled=False))
    assert out == ReasonCode.MR_SHORT_DISABLED


def test_long_disabled_skips():
    out = mr.compute_mr_placement(entry=98.0, mean=100.0, cfg=_cfg(mr_long_enabled=False))
    assert out == ReasonCode.MR_LONG_DISABLED


def test_no_edge_skips():
    # entry within min_edge_pct of mean -> MR_NO_EDGE from check_geometry
    out = mr.compute_mr_placement(entry=100.05, mean=100.0, cfg=_cfg(mr_min_edge_pct=1.0))
    assert out == ReasonCode.MR_NO_EDGE


def test_default_tight_stop_when_unset():
    # mr_tight_stop_pct None -> default 8.0 (matches live _compute_mr_params)
    out = mr.compute_mr_placement(entry=102.0, mean=100.0, cfg=_cfg(mr_tight_stop_pct=None))
    assert not isinstance(out, ReasonCode)
    assert out["stop_loss_pct"] == 8.0


def test_inverted_geometry_skips():
    # a tight SL wider than the (capture-scaled) TP -> inverted geometry
    out = mr.compute_mr_placement(entry=101.0, mean=100.0,
                                  cfg=_cfg(mr_tight_stop_pct=900.0))
    assert isinstance(out, ReasonCode)  # geometry guard fired


def test_matches_live_param_shape():
    # The returned dict keys must equal what the live place_trade path consumes.
    out = mr.compute_mr_placement(entry=102.0, mean=100.0, cfg=_cfg())
    assert set(out.keys()) == {
        "signal_direction", "leverage", "take_profit_pct", "stop_loss_pct", "capital_pct"}
