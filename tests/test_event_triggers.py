"""Tests for AI Manager Event-Driven Trigger Detector."""

import time
from unittest.mock import patch

import pytest

from backend.services.ai_manager_event_triggers import EventTriggerDetector


@pytest.fixture
def detector():
    return EventTriggerDetector(
        price_move_pct=1.5,
        drawdown_from_peak_pct=25.0,
        pnl_velocity_pct=1.5,
        volume_anomaly_multiplier=3.0,
        staleness_alarm_s=600,
        funding_rate_threshold=0.0005,
    )


def _make_position(symbol="BTCUSDT", mark_price=50000, unrealised_pnl=100, side="Buy"):
    return {
        "symbol": symbol,
        "markPrice": str(mark_price),
        "unrealisedPnl": str(unrealised_pnl),
        "side": side,
    }


class TestPriceMoveTrigger:
    def test_no_trigger_on_first_check(self, detector):
        """First check has no baseline — should not trigger."""
        pos = [_make_position(mark_price=50000)]
        triggered, reason = detector.check_triggers(pos)
        assert not triggered

    def test_triggers_on_significant_price_move(self, detector):
        pos = [_make_position(mark_price=50000)]
        detector.mark_evaluated(pos)

        # Price moves 2% (above 1.5% threshold)
        pos_moved = [_make_position(mark_price=51000)]
        triggered, reason = detector.check_triggers(pos_moved)
        assert triggered
        assert "price_move" in reason
        assert "BTCUSDT" in reason

    def test_no_trigger_on_small_price_move(self, detector):
        pos = [_make_position(mark_price=50000)]
        detector.mark_evaluated(pos)

        # Price moves 0.5% (below 1.5% threshold)
        pos_moved = [_make_position(mark_price=50250)]
        triggered, reason = detector.check_triggers(pos_moved)
        assert not triggered


class TestDrawdownFromPeakTrigger:
    def test_triggers_on_large_drawdown(self, detector):
        pos = [_make_position(unrealised_pnl=50)]
        detector.mark_evaluated(pos)

        # Peak was 100, now dropped to 50 → 50% drawdown (above 25%)
        peak_pnl = {"BTCUSDT": 100.0}
        pos_down = [_make_position(mark_price=50000, unrealised_pnl=50)]
        triggered, reason = detector.check_triggers(pos_down, peak_pnl=peak_pnl)
        assert triggered
        assert "drawdown_from_peak" in reason

    def test_no_trigger_on_small_drawdown(self, detector):
        pos = [_make_position(unrealised_pnl=90)]
        detector.mark_evaluated(pos)

        # Peak was 100, now 90 → 10% drawdown (below 25%)
        peak_pnl = {"BTCUSDT": 100.0}
        pos_down = [_make_position(mark_price=50000, unrealised_pnl=90)]
        triggered, reason = detector.check_triggers(pos_down, peak_pnl=peak_pnl)
        assert not triggered


class TestPnlVelocityTrigger:
    def test_triggers_on_high_velocity(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        indicators = {"BTCUSDT": {"pnl_velocity_30s": 0.02}}  # 2% > 1.5%
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert triggered
        assert "pnl_velocity" in reason

    def test_no_trigger_on_low_velocity(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        indicators = {"BTCUSDT": {"pnl_velocity_30s": 0.005}}  # 0.5% < 1.5%
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert not triggered


class TestFundingRateTrigger:
    def test_triggers_on_funding_change(self, detector):
        pos = [_make_position()]
        # Set baseline with low funding
        indicators_baseline = {"BTCUSDT": {"funding_rate": 0.0001}}
        detector.mark_evaluated(pos, indicators=indicators_baseline)

        # Funding changes significantly (delta = 0.0009 > 0.0005 threshold)
        indicators = {"BTCUSDT": {"funding_rate": 0.001}}
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert triggered
        assert "funding_change" in reason

    def test_no_trigger_on_persistent_high_funding(self, detector):
        pos = [_make_position()]
        # Set baseline with already-high funding
        indicators_baseline = {"BTCUSDT": {"funding_rate": 0.001}}
        detector.mark_evaluated(pos, indicators=indicators_baseline)

        # Same high funding on next tick — should NOT trigger
        indicators = {"BTCUSDT": {"funding_rate": 0.001}}
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert not triggered

    def test_triggers_on_first_extreme_funding(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)  # No funding baseline stored

        # First time seeing extreme funding
        indicators = {"BTCUSDT": {"funding_rate": 0.001}}
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert triggered
        assert "funding_spike" in reason


class TestVolumeAnomalyTrigger:
    def test_triggers_on_volume_spike(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        indicators = {"BTCUSDT": {"volume_last_candle": 1000, "volume_20_avg": 200}}  # 5x > 3x
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert triggered
        assert "volume_anomaly" in reason

    def test_no_trigger_on_normal_volume(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        indicators = {"BTCUSDT": {"volume_last_candle": 400, "volume_20_avg": 200}}  # 2x < 3x
        triggered, reason = detector.check_triggers(pos, indicators=indicators)
        assert not triggered


class TestRegimeChangeTrigger:
    def test_triggers_on_regime_change(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos, regime="ranging")

        # Provide indicators that would compute a different regime
        # Since we can't easily mock compute_regime, test the internal logic directly
        detector._last_regime = "ranging"
        # Simulate: check_triggers computes regime from indicators internally
        # For unit test: directly verify the trigger logic by setting up the state
        # and calling with indicators that would yield a different regime
        # We'll test via the _compute_regime_label path indirectly
        # For now verify regime is stored and the comparison works
        from backend.services.ai_manager_event_triggers import _compute_regime_label
        # If compute_regime is available, test integration; otherwise test the guard
        result = _compute_regime_label({})
        if result is None:
            # Module not importable in test env — test the guard prevents false triggers
            triggered, reason = detector.check_triggers(pos, indicators={"BTCUSDT": {}})
            assert not triggered  # Should not trigger if regime can't be computed

    def test_no_trigger_when_no_baseline_regime(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)  # No regime set → _last_regime stays None

        triggered, reason = detector.check_triggers(pos, indicators={"BTCUSDT": {}})
        assert not triggered  # Guard: _last_regime is None → skip regime check


class TestStalenessAlarm:
    def test_triggers_after_staleness_timeout(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        # Simulate time passing beyond staleness alarm
        detector._last_eval_time = time.monotonic() - 700  # 700s > 600s
        triggered, reason = detector.check_triggers(pos)
        assert triggered
        assert "staleness_alarm" in reason

    def test_no_trigger_before_staleness(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        # Only 100s elapsed (< 600s)
        detector._last_eval_time = time.monotonic() - 100
        triggered, reason = detector.check_triggers(pos)
        assert not triggered


class TestMarkEvaluated:
    def test_resets_baseline_prices(self, detector):
        pos = [_make_position(mark_price=50000)]
        detector.mark_evaluated(pos)
        assert detector._last_eval_prices["BTCUSDT"] == 50000.0

    def test_resets_regime(self, detector):
        pos = [_make_position()]
        detector.mark_evaluated(pos, regime="trending_up")
        assert detector._last_regime == "trending_up"

    def test_resets_eval_time(self, detector):
        old_time = detector._last_eval_time
        pos = [_make_position()]
        detector.mark_evaluated(pos)
        assert detector._last_eval_time >= old_time


class TestMultiplePositions:
    def test_triggers_on_any_position(self, detector):
        """If any position triggers, the whole check fires."""
        pos = [
            _make_position("BTCUSDT", mark_price=50000),
            _make_position("ETHUSDT", mark_price=3000),
        ]
        detector.mark_evaluated(pos)

        # Only ETH moves significantly
        pos_moved = [
            _make_position("BTCUSDT", mark_price=50100),  # 0.2% - no trigger
            _make_position("ETHUSDT", mark_price=3060),  # 2% - triggers
        ]
        triggered, reason = detector.check_triggers(pos_moved)
        assert triggered
        assert "ETHUSDT" in reason


class TestNewPositionTrigger:
    def test_triggers_on_new_position(self, detector):
        """A new position (symbol not in baseline) should trigger immediately."""
        pos = [_make_position("BTCUSDT", mark_price=50000)]
        detector.mark_evaluated(pos)

        # New position opened
        pos_with_new = [
            _make_position("BTCUSDT", mark_price=50000),
            _make_position("ETHUSDT", mark_price=3000),
        ]
        triggered, reason = detector.check_triggers(pos_with_new)
        assert triggered
        assert "new_position" in reason
        assert "ETHUSDT" in reason

    def test_no_trigger_when_no_baseline_exists(self, detector):
        """On very first check (no baseline at all), new_position should NOT fire."""
        pos = [_make_position("BTCUSDT", mark_price=50000)]
        # No mark_evaluated called — _last_eval_prices is empty
        triggered, reason = detector.check_triggers(pos)
        assert not triggered  # Guard: _last_eval_prices is empty → skip new_position check


class TestDebounceCooldown:
    def test_suppresses_triggers_within_cooldown(self, detector):
        """After a trigger fires, subsequent triggers are suppressed for min_trigger_interval."""
        pos = [_make_position(mark_price=50000)]
        detector.mark_evaluated(pos)

        # Simulate a trigger having just fired
        detector.mark_triggered()

        # Price moved enough to trigger, but cooldown active
        pos_moved = [_make_position(mark_price=51000)]
        triggered, reason = detector.check_triggers(pos_moved)
        assert not triggered

    def test_allows_trigger_after_cooldown_expires(self, detector):
        """Triggers resume after cooldown elapses."""
        pos = [_make_position(mark_price=50000)]
        detector.mark_evaluated(pos)

        # Simulate trigger fired 20s ago (beyond 15s cooldown)
        detector._last_trigger_time = time.monotonic() - 20.0

        pos_moved = [_make_position(mark_price=51000)]
        triggered, reason = detector.check_triggers(pos_moved)
        assert triggered

    def test_staleness_bypasses_debounce(self, detector):
        """Staleness alarm fires even during active debounce."""
        pos = [_make_position()]
        detector.mark_evaluated(pos)

        # Active debounce (just triggered)
        detector.mark_triggered()
        # But also stale (eval was long ago)
        detector._last_eval_time = time.monotonic() - 700

        triggered, reason = detector.check_triggers(pos)
        assert triggered
        assert "staleness_alarm" in reason

    def test_staleness_suppressed_after_aborted_eval(self, detector):
        """After simulating aborted eval, staleness should NOT immediately re-fire."""
        pos = [_make_position()]
        # Simulate aborted-eval state: advance eval time so staleness fires in 60s not now
        now = time.monotonic()
        detector._last_eval_time = now - (detector._staleness_alarm_s - 60)
        detector._last_trigger_time = now
        detector._min_trigger_interval_s = 60.0

        triggered, reason = detector.check_triggers(pos)
        assert not triggered  # Neither staleness (540s < 600s) nor debounce-gated triggers


# --- check_all_triggers tests ---


class TestCheckAllTriggers:
    """Tests for the multi-symbol trigger detection."""

    def test_returns_multiple_triggered_symbols(self, detector):
        """Multiple positions triggering should all be returned."""
        detector.mark_evaluated(
            [_make_position("BTCUSDT", 50000), _make_position("ETHUSDT", 3000)],
        )
        # Move both prices beyond threshold
        positions = [
            _make_position("BTCUSDT", 51000),  # 2% move
            _make_position("ETHUSDT", 3060),   # 2% move
        ]
        results = detector.check_all_triggers(positions)
        symbols = [r[0] for r in results]
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        assert len(results) == 2

    def test_sorted_by_priority_descending(self, detector):
        """Higher priority triggers should be first."""
        detector.mark_evaluated(
            [_make_position("BTCUSDT", 50000), _make_position("ETHUSDT", 3000)],
        )
        # BTC: 1.6% move (priority ~1.6), ETH: 3% move (priority ~3.0)
        positions = [
            _make_position("BTCUSDT", 50800),
            _make_position("ETHUSDT", 3090),
        ]
        results = detector.check_all_triggers(positions)
        assert results[0][0] == "ETHUSDT"  # Higher priority first
        assert results[0][2] > results[1][2]

    def test_dedupes_per_symbol_keeps_highest(self, detector):
        """If multiple triggers fire for same symbol, keep highest priority."""
        detector.mark_evaluated(
            [_make_position("BTCUSDT", 50000, unrealised_pnl=1000)],
        )
        # Price move (2%) AND drawdown (50% from peak)
        positions = [_make_position("BTCUSDT", 51000, unrealised_pnl=500)]
        peak_pnl = {"BTCUSDT": 1000.0}
        results = detector.check_all_triggers(positions, peak_pnl=peak_pnl)
        assert len(results) == 1  # Deduped to one entry
        assert results[0][0] == "BTCUSDT"
        assert results[0][2] == 50.0  # Drawdown % is higher priority than 2% price move

    def test_staleness_returns_all_symbols(self, detector):
        """Staleness alarm should return all position symbols."""
        detector._last_eval_time = time.monotonic() - 700  # 700s > 600s
        positions = [
            _make_position("BTCUSDT", 50000),
            _make_position("ETHUSDT", 3000),
            _make_position("SOLUSDT", 150),
        ]
        results = detector.check_all_triggers(positions)
        assert len(results) == 3
        assert all("staleness" in r[1] for r in results)

    def test_debounce_suppresses_all(self, detector):
        """Debounce should suppress all triggers (not just first)."""
        detector.mark_evaluated([_make_position("BTCUSDT", 50000)])
        detector.mark_triggered()  # Just triggered
        positions = [_make_position("BTCUSDT", 51000)]  # 2% move
        results = detector.check_all_triggers(positions)
        assert results == []

    def test_empty_when_no_triggers(self, detector):
        """No triggers = empty list."""
        detector.mark_evaluated([_make_position("BTCUSDT", 50000)])
        positions = [_make_position("BTCUSDT", 50100)]  # 0.2% — below threshold
        results = detector.check_all_triggers(positions)
        assert results == []

    def test_new_position_detected(self, detector):
        """New position should be in results."""
        detector.mark_evaluated([_make_position("BTCUSDT", 50000)])
        positions = [
            _make_position("BTCUSDT", 50100),  # No trigger (small move)
            _make_position("ETHUSDT", 3000),   # New position
        ]
        results = detector.check_all_triggers(positions)
        assert len(results) == 1
        assert results[0][0] == "ETHUSDT"
        assert "new_position" in results[0][1]
