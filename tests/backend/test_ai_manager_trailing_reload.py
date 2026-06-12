"""WF-4: reload_config must cancel in-flight trailing loops when trailing_enabled
transitions True -> False, so a per-scan override that disables trailing on a LIVE
task actually stops existing trailing loops (not just blocks new ones)."""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_task import AIManagerTask
from backend.services.ai_manager_event_triggers import EventTriggerDetector


def _minimal_task(trailing_enabled: bool) -> AIManagerTask:
    """Build an AIManagerTask shell with only the attributes reload_config touches —
    avoids the heavy real constructor / external deps."""
    task = object.__new__(AIManagerTask)
    task._config = AIManagerConfig(trailing_enabled=trailing_enabled)
    task._event_trigger = EventTriggerDetector(
        price_move_pct=1.5, drawdown_from_peak_pct=25.0, pnl_velocity_pct=1.5,
        volume_anomaly_multiplier=3.0, staleness_alarm_s=600, funding_rate_threshold=0.0005,
    )
    task._rapid_cycle_handle = None
    task._trigger_queue = []
    task._trigger_symbol = None
    task._drain_count = 0
    task._active_trailing = {}
    return task


def test_reload_disabling_trailing_cancels_active_loops():
    task = _minimal_task(trailing_enabled=True)
    ts = MagicMock()
    task._active_trailing = {"BTCUSDT": ts}

    task.reload_config(AIManagerConfig(trailing_enabled=False))

    ts.cancel.assert_called_once()
    assert task._active_trailing == {}


def test_reload_keeping_trailing_on_does_not_cancel():
    task = _minimal_task(trailing_enabled=True)
    ts = MagicMock()
    task._active_trailing = {"BTCUSDT": ts}

    task.reload_config(AIManagerConfig(trailing_enabled=True))

    ts.cancel.assert_not_called()
    assert "BTCUSDT" in task._active_trailing


def test_reload_enabling_trailing_does_not_cancel():
    task = _minimal_task(trailing_enabled=False)
    ts = MagicMock()
    task._active_trailing = {"BTCUSDT": ts}  # unusual, but must not be force-cancelled

    task.reload_config(AIManagerConfig(trailing_enabled=True))

    ts.cancel.assert_not_called()
