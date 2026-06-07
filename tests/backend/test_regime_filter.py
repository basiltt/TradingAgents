"""Tests for F1 session + BTC-vol gate predicates (Phase 3)."""

from datetime import datetime, timedelta, timezone

from backend.services.regime_filter import gate_session, gate_btc_vol, btc_vol_unavailable
from backend.services.scan_context import ScanContext
from backend.services.strategy_reason_codes import ReasonCode


def _utc(hour, minute=0):
    return datetime(2026, 6, 7, hour, minute, 0, tzinfo=timezone.utc)


# ── session gate (FR-010, EC-01, T-11) ──

def _f1_cfg(**kw):
    base = {"regime_filter_enabled": True, "session_filter_enabled": True}
    base.update(kw)
    return base


def test_session_off_when_umbrella_off():
    cfg = {"regime_filter_enabled": False, "session_filter_enabled": True,
           "session_blocked_hours_utc": [9]}
    assert gate_session(cfg, _utc(9)) is None


def test_session_blocks_in_window():
    cfg = _f1_cfg(session_blocked_hours_utc=[1, 6, 7, 8, 9, 10, 11, 12])
    assert gate_session(cfg, _utc(9)) == ReasonCode.SESSION_FILTER


def test_session_allows_outside_window():
    cfg = _f1_cfg(session_blocked_hours_utc=[1, 6, 7, 8, 9, 10, 11, 12])
    assert gate_session(cfg, _utc(15)) is None


def test_session_boundary_hh00_and_hh59():
    cfg = _f1_cfg(session_blocked_hours_utc=[9])
    assert gate_session(cfg, _utc(9, 0)) == ReasonCode.SESSION_FILTER
    assert gate_session(cfg, _utc(9, 59)) == ReasonCode.SESSION_FILTER
    assert gate_session(cfg, _utc(8, 59)) is None
    assert gate_session(cfg, _utc(10, 0)) is None


def test_session_uses_placement_utc_not_naive_local():
    # A +02 local time of 03:30 is UTC 01:30 -> blocked when hour 1 is blocked.
    cfg = _f1_cfg(session_blocked_hours_utc=[1])
    local_plus2 = datetime(2026, 6, 7, 3, 30, 0, tzinfo=timezone(timedelta(hours=2)))
    assert gate_session(cfg, local_plus2) == ReasonCode.SESSION_FILTER


def test_session_allowlist_mode():
    cfg = _f1_cfg(session_allowed_hours_utc=[13, 14, 15])
    assert gate_session(cfg, _utc(14)) is None        # allowed
    assert gate_session(cfg, _utc(9)) == ReasonCode.SESSION_FILTER  # outside allowed


# ── BTC vol gate (FR-012, FR-014, fail-open) ──

def _ctx_with_vol(value, interval="1h", lookback=14, unavailable=False):
    return ScanContext(
        btc={(interval, lookback): {"regime": "ranging", "vol_value": value, "unavailable": unavailable}},
        computed_at=_utc(12),
    )


def _vol_cfg(**kw):
    base = {"regime_filter_enabled": True, "btc_vol_filter_enabled": True,
            "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14}
    base.update(kw)
    return base


def test_vol_suppresses_below_min():
    cfg = _vol_cfg(btc_vol_min_threshold=0.8)
    assert gate_btc_vol(cfg, _ctx_with_vol(0.5)) == ReasonCode.BTC_VOL_FILTER


def test_vol_suppresses_above_max():
    cfg = _vol_cfg(btc_vol_max_threshold=2.0)
    assert gate_btc_vol(cfg, _ctx_with_vol(2.5)) == ReasonCode.BTC_VOL_FILTER


def test_vol_allows_inside_band():
    cfg = _vol_cfg(btc_vol_min_threshold=0.8, btc_vol_max_threshold=2.0)
    assert gate_btc_vol(cfg, _ctx_with_vol(1.2)) is None


def test_vol_boundary_equality_allows():
    cfg = _vol_cfg(btc_vol_min_threshold=0.8, btc_vol_max_threshold=2.0)
    assert gate_btc_vol(cfg, _ctx_with_vol(0.8)) is None   # exactly at lo
    assert gate_btc_vol(cfg, _ctx_with_vol(2.0)) is None   # exactly at hi


def test_vol_unavailable_fails_open():
    cfg = _vol_cfg(btc_vol_min_threshold=0.8)
    unavail = ScanContext(btc={("1h", 14): {"regime": "unknown", "vol_value": None, "unavailable": True}},
                          computed_at=_utc(12))
    assert gate_btc_vol(cfg, unavail) is None              # proceeds (fail-open)
    assert btc_vol_unavailable(cfg, unavail) is True       # but trace flag set


def test_vol_off_when_umbrella_off():
    cfg = {"regime_filter_enabled": False, "btc_vol_filter_enabled": True,
           "btc_vol_min_threshold": 0.8, "btc_vol_interval": "1h", "btc_vol_lookback_candles": 14}
    assert gate_btc_vol(cfg, _ctx_with_vol(0.1)) is None
