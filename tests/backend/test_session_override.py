"""Tests for FR-066 / SD20: one-time manual session-filter override (T-23).

The override:
  * bypasses BOTH F1 sub-modes (session + vol) for exactly one scan,
  * is honoured only on manual/run-now scans (never scheduled),
  * is non-persistent (lives on the per-scan config copy; auto-reverts next scan),
  * tags overridden entries f1_active=False so they're excluded from efficacy stats.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.services import regime_filter as rf
from backend.services.scan_context import ScanContext
from backend.services.strategy_reason_codes import ReasonCode


def _ctx_vol(v):
    return ScanContext(
        btc={("1h", 14): {"regime": "volatile", "vol_value": v, "unavailable": False}},
        means={}, prices={}, computed_at=datetime.now(timezone.utc))


def _f1_cfg(**kw):
    base = {"regime_filter_enabled": True, "session_filter_enabled": True,
            "session_blocked_hours_utc": list(range(24)),  # block ALL hours
            "btc_vol_filter_enabled": True, "btc_vol_min_threshold": 5.0,
            "btc_vol_max_threshold": 9.0}
    base.update(kw)
    return base


# --- gate bypass -----------------------------------------------------------------

def test_session_gate_blocks_without_override():
    cfg = _f1_cfg()
    now = datetime(2026, 6, 7, 8, 0, tzinfo=timezone.utc)  # hour 8 is blocked
    assert rf.gate_session(cfg, now) == ReasonCode.SESSION_FILTER


def test_session_gate_bypassed_with_override():
    cfg = _f1_cfg(_session_filter_override_active=True)
    now = datetime(2026, 6, 7, 8, 0, tzinfo=timezone.utc)
    assert rf.gate_session(cfg, now) is None


def test_vol_gate_blocks_without_override():
    cfg = _f1_cfg()
    # vol 2.0 is below the [5,9] band -> suppressed
    assert rf.gate_btc_vol(cfg, _ctx_vol(2.0)) == ReasonCode.BTC_VOL_FILTER


def test_vol_gate_also_bypassed_with_override():
    # SD20: the override bypasses BOTH sub-modes, not just session.
    cfg = _f1_cfg(_session_filter_override_active=True)
    assert rf.gate_btc_vol(cfg, _ctx_vol(2.0)) is None


# --- non-persistence / trigger gating (the REAL start_scan stamping helper) --------

from backend.services.features import apply_session_override as _stamp_impl


def _stamp(config, auto_configs, trigger):
    # Imports the REAL helper start_scan calls (no mirrored copy that could drift from
    # the scheduled-bypass guard).
    return _stamp_impl(config, auto_configs, trigger)


def test_override_stamped_on_manual_scan():
    cfgs = [_f1_cfg()]
    n = _stamp({"session_filter_override": True}, cfgs, "manual")
    assert cfgs[0]["_session_filter_override_active"] is True
    assert n == 1


def test_override_stamped_on_run_now_scan():
    cfgs = [_f1_cfg()]
    _stamp({"session_filter_override": True}, cfgs, "run_now")
    assert cfgs[0]["_session_filter_override_active"] is True


def test_override_ignored_on_scheduled_scan():
    # A saved schedule must NOT be able to carry a persistent bypass.
    cfgs = [_f1_cfg()]
    n = _stamp({"session_filter_override": True}, cfgs, "scheduled")
    assert "_session_filter_override_active" not in cfgs[0]
    assert n == 0


def test_override_not_stamped_when_flag_absent():
    cfgs = [_f1_cfg()]
    _stamp({}, cfgs, "manual")
    assert "_session_filter_override_active" not in cfgs[0]


def test_override_skips_non_f1_configs():
    cfgs = [{"regime_filter_enabled": False}]  # F1 off -> nothing to bypass
    n = _stamp({"session_filter_override": True}, cfgs, "manual")
    assert "_session_filter_override_active" not in cfgs[0]
    assert n == 0


def test_override_auto_reverts_next_scan():
    # Scan 1 with override -> stamped. Scan 2 uses FRESH config copies without the
    # override flag -> the bypass does not carry over (non-persistence).
    scan1 = [_f1_cfg()]
    _stamp({"session_filter_override": True}, scan1, "manual")
    assert scan1[0]["_session_filter_override_active"] is True

    scan2 = [_f1_cfg()]  # fresh copy, override not requested
    _stamp({"session_filter_override": False}, scan2, "manual")
    assert "_session_filter_override_active" not in scan2[0]
    now = datetime(2026, 6, 7, 8, 0, tzinfo=timezone.utc)
    assert rf.gate_session(scan2[0], now) == ReasonCode.SESSION_FILTER  # F1 active again


# --- f1_active efficacy exclusion (mirrors the place_trade f1_active expression) --

from backend.services.regime_filter import compute_f1_active as _f1_active


def test_overridden_entry_is_not_f1_active():
    cfg = _f1_cfg(_session_filter_override_active=True)
    assert _f1_active(cfg) is False  # excluded from before/after efficacy stats


def test_normal_f1_entry_is_f1_active():
    assert _f1_active(_f1_cfg()) is True


def test_umbrella_on_but_no_subgate_is_not_f1_active():
    # regime_filter_enabled on, but both sub-gates off => F1 never acts => not f1-active.
    cfg = _f1_cfg(session_filter_enabled=False, btc_vol_filter_enabled=False)
    assert _f1_active(cfg) is False
