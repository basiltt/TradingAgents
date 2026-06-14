"""Tests for the post-scan revert kill-switch snapshot + cap values (P0R2 fixes)."""
import pytest

from backend.services import post_scan_flags as flags
from backend.services.bybit_endpoints import ENDPOINT_PER_SECOND_CAP
from backend.services.bybit_rate_gate import BybitRateGate


@pytest.fixture(autouse=True)
def _reset():
    flags.reset_for_tests()
    yield
    flags.reset_for_tests()


class TestPostScanFlags:
    def test_default_state_corrected_behavior_active(self):
        assert flags.channel_fix_active() is True
        assert flags.per_endpoint_limiter_active() is True
        assert flags.fanout_disabled() is False

    def test_all_sentinel_does_not_revert_fixes(self):
        """A fail-closed read ({"__all__": True}) must NOT revert the correctness
        fixes — they read their own key, not the master kill. A DB blip cannot
        silently route market reads back onto the private budget."""
        flags.apply_snapshot({"__all__": True})
        assert flags.channel_fix_active() is True
        assert flags.per_endpoint_limiter_active() is True
        assert flags.fanout_disabled() is False

    def test_explicit_revert_flips_behavior(self):
        flags.apply_snapshot({"rate_gate_channel_fix": True})
        assert flags.channel_fix_active() is False
        flags.apply_snapshot({"rate_gate_per_endpoint_limiter": True})
        assert flags.per_endpoint_limiter_active() is False
        flags.apply_snapshot({"post_scan_fanout_disabled": True})
        assert flags.fanout_disabled() is True

    def test_revert_then_restore(self):
        flags.apply_snapshot({"post_scan_fanout_disabled": True})
        assert flags.fanout_disabled() is True
        flags.apply_snapshot({})  # row removed
        assert flags.fanout_disabled() is False


class TestCapValues:
    def test_pinned_cap_values(self):
        """The shipped per-endpoint caps must stay at their safe-floor values
        (a regression to e.g. 80 would defeat the per-UID ban guard)."""
        assert ENDPOINT_PER_SECOND_CAP["order_create"] == 8
        assert ENDPOINT_PER_SECOND_CAP["order_cancel"] == 8
        assert ENDPOINT_PER_SECOND_CAP["order_amend"] == 8
        assert ENDPOINT_PER_SECOND_CAP["set_leverage"] == 8
        assert ENDPOINT_PER_SECOND_CAP["set_trading_stop"] == 8
        assert ENDPOINT_PER_SECOND_CAP["position_list"] == 40
        assert ENDPOINT_PER_SECOND_CAP["wallet"] == 40
        assert ENDPOINT_PER_SECOND_CAP["order_query"] == 20
        assert ENDPOINT_PER_SECOND_CAP["market"] is None

    def test_default_gate_loads_caps_from_registry(self):
        gate = BybitRateGate()
        assert gate._endpoint_caps.get("order_create") == 8
        # market (None) must be filtered out of the active caps.
        assert "market" not in gate._endpoint_caps
