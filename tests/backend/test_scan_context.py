"""Tests for the ScanContext frozen dataclass (TASK-0.4)."""

from datetime import datetime, timedelta, timezone

from backend.services.scan_context import ScanContext, _EPOCH


def _now():
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def test_scan_context_empty_degraded():
    ctx = ScanContext.empty(degraded=True)
    assert ctx.degraded is True
    assert ctx.btc == {} and ctx.means == {} and ctx.prices == {}
    assert ctx.computed_at == _EPOCH


def test_empty_carries_kill_dict():
    # R3-F1: empty() must carry the kill dict so kills work without precompute.
    ctx = ScanContext.empty(degraded=False, kill={"__all__": True})
    assert ctx.is_killed("f2") is True
    assert ctx.is_killed("anything") is True


def test_is_killed_master_and_per_feature():
    ctx = ScanContext(kill={"f2": True})
    assert ctx.is_killed("f2") is True
    assert ctx.is_killed("f1") is False
    ctx_all = ScanContext(kill={"__all__": True})
    assert ctx_all.is_killed("f1") is True


def test_routing_regime_unknown_when_absent_or_degraded():
    ctx = ScanContext(btc={("1h", 14): {"regime": "ranging", "vol_value": 1.0, "unavailable": False}},
                      computed_at=_now())
    assert ctx.routing_regime("1h", 14) == "ranging"
    assert ctx.routing_regime("4h", 14) == "unknown"  # absent
    degraded = ScanContext.empty(degraded=True)
    assert degraded.routing_regime("1h", 14) == "unknown"


def test_is_stale_boundary():
    now = _now()
    fresh = ScanContext(computed_at=now - timedelta(minutes=29), degraded=False)
    stale = ScanContext(computed_at=now - timedelta(minutes=31), degraded=False)
    assert fresh.is_stale(now, 30) is False
    assert stale.is_stale(now, 30) is True


def test_degraded_always_stale():
    # R2-F5: a degraded context (epoch computed_at) is always stale => F2 fail-closed.
    ctx = ScanContext.empty(degraded=True)
    assert ctx.is_stale(_now(), 30) is True
    assert ctx.is_stale(_now(), 100000) is True  # even with huge TTL


def test_get_mean_and_price():
    ctx = ScanContext(means={("BTCUSDT", 20, "1h"): 50000.0}, prices={"BTCUSDT": 50100.0})
    assert ctx.get_mean("BTCUSDT", 20, "1h") == 50000.0
    assert ctx.get_mean("ETHUSDT", 20, "1h") is None
    assert ctx.get_price("BTCUSDT") == 50100.0
    assert ctx.get_price("ETHUSDT") is None


def test_frozen_immutable():
    ctx = ScanContext()
    try:
        ctx.degraded = True  # type: ignore
        assert False, "ScanContext should be frozen"
    except Exception:
        pass
