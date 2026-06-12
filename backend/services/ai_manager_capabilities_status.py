"""Aggregates capability health status for the AI Manager dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# NOTE: This registry powers the AI Manager *dashboard health view* and uses its own
# display-oriented `key` vocabulary (e.g. "mtf_analysis", "sweep_detection") that
# differs from the per-scan capability TOGGLE keys in `ai_manager_capability_map.py`
# (e.g. "mtf", "sweep_defense"). What ties them together is `config_flag`: each entry
# maps to the SAME AIManagerConfig field the toggles set, so a per-scan override (read
# here via task._config) is reflected truthfully on the dashboard. Keep config_flag in
# sync with CAPABILITY_FLAG_MAP values. `episodic_memory` has config_flag=None (always
# on, no toggle). If you add a user-facing capability, add it to BOTH this registry and
# the toggle set/map so the dashboard doesn't misreport it.
CAPABILITY_REGISTRY: list[dict[str, Any]] = [
    {"key": "mtf_analysis", "display_name": "Multi-Timeframe Analysis", "config_flag": "mtf_enabled"},
    {"key": "correlation", "display_name": "Correlation & Clustering", "config_flag": "correlation_enabled"},
    {"key": "orderbook", "display_name": "Order Book Monitoring", "config_flag": "orderbook_enabled"},
    {"key": "regime_detection", "display_name": "Regime Enhancement", "config_flag": "regime_enhanced"},
    {"key": "sweep_detection", "display_name": "Sweep / Stop-Hunt Defense", "config_flag": "sweep_defense_enabled"},
    {"key": "episodic_memory", "display_name": "Pattern Learning & Memory", "config_flag": None},
    {"key": "emergency_close", "display_name": "Emergency Close", "config_flag": "emergency_close_enabled"},
    {"key": "trailing", "display_name": "Trailing TP/SL", "config_flag": "trailing_enabled"},
    {"key": "event_driven", "display_name": "Event-Driven Evaluation", "config_flag": "event_driven_enabled"},
]

DEGRADATION_MAP: dict[int, list[str]] = {
    1: [],
    2: ["correlation", "orderbook", "mtf_analysis"],
    3: ["correlation", "orderbook", "mtf_analysis", "episodic_memory", "sweep_detection"],
    4: ["correlation", "orderbook", "mtf_analysis", "episodic_memory", "sweep_detection", "regime_detection"],
}


class CapabilitiesStatusAggregator:
    """Builds the AI-manager capability health view from config, degradation tier, and task state."""

    def __init__(
        self,
        config: dict[str, Any],
        degradation_tier: int,
        task_state: dict[str, Any],
        evaluation_interval_s: int,
        next_eval_at: datetime | None,
    ):
        self._config = config
        self._tier = degradation_tier
        self._task_state = task_state
        self._eval_interval = evaluation_interval_s
        self._next_eval_at = next_eval_at

    def get_capabilities(self) -> list[dict[str, Any]]:
        """Return per-capability status rows (enabled, healthy/degraded/disabled, next trigger).

        A capability is "disabled" by config flag, "degraded" if cut at the current
        degradation tier, else "healthy".
        """
        degraded_keys: set[str] = set()
        for tier_level in range(1, self._tier + 1):
            degraded_keys.update(DEGRADATION_MAP.get(tier_level, []))

        now = datetime.now(timezone.utc)
        results = []
        for cap in CAPABILITY_REGISTRY:
            key = cap["key"]
            config_flag = cap["config_flag"]

            enabled = True
            if config_flag and not self._config.get(config_flag, True):
                enabled = False

            if not enabled:
                status = "disabled"
            elif key in degraded_keys:
                status = "degraded"
            else:
                status = "healthy"

            last_triggered = self._task_state.get(f"last_triggered_{key}")
            trigger_count = self._task_state.get(f"trigger_count_{key}", 0)

            countdown = None
            if self._next_eval_at and enabled and status != "disabled":
                delta = (self._next_eval_at - now).total_seconds()
                countdown = max(0, int(delta))

            armed = False
            if key == "sweep_detection":
                armed = bool(self._task_state.get("active_sweep_symbols"))

            if not enabled:
                condition = "Disabled by configuration"
            elif status == "degraded":
                condition = f"Degraded (tier {self._tier})"
            elif countdown is not None:
                condition = f"Next evaluation in {countdown}s"
            else:
                condition = "Waiting for positions"

            results.append({
                "capability_key": key,
                "display_name": cap["display_name"],
                "enabled": enabled,
                "status": status,
                "last_triggered_at": last_triggered.isoformat() if last_triggered else None,
                "trigger_count_session": trigger_count,
                "next_trigger_condition": condition,
                "countdown_seconds": countdown,
                "armed": armed,
            })
        return results

    def get_response(self) -> dict[str, Any]:
        """Return the full dashboard payload: capabilities plus tier and next-eval countdown."""
        countdown = 0
        if self._next_eval_at:
            now = datetime.now(timezone.utc)
            countdown = max(0, int((self._next_eval_at - now).total_seconds()))
        return {
            "capabilities": self.get_capabilities(),
            "degradation_tier": self._tier,
            "evaluation_interval_s": self._eval_interval,
            "next_evaluation_in_s": countdown,
        }
