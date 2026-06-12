"""Pure mapping from per-scan capability toggles to AIManagerConfig flags.

No I/O — unit-testable in isolation. Used by auto_trade_service to layer a
per-scan capability override onto the account's AIManagerConfig without
persisting it.
"""
from __future__ import annotations

from typing import Any

from backend.ai_manager_schemas import AIManagerConfig
from backend.schemas import AIManagerCapabilityToggles

# toggle key -> AIManagerConfig flag name
CAPABILITY_FLAG_MAP: dict[str, str] = {
    "mtf": "mtf_enabled",
    "orderbook": "orderbook_enabled",
    "sweep_defense": "sweep_defense_enabled",
    "correlation": "correlation_enabled",
    "regime_enhanced": "regime_enhanced",
    "event_driven": "event_driven_enabled",
    "trailing": "trailing_enabled",
    "emergency_close": "emergency_close_enabled",
}


def apply_capability_overrides(
    config: AIManagerConfig,
    toggles: "AIManagerCapabilityToggles | dict[str, Any] | None",
) -> AIManagerConfig:
    """Return a copy of `config` with the 8 capability flags overridden by `toggles`.

    No-op (returns an equivalent copy) when `toggles` is None. A dict is validated
    through AIManagerCapabilityToggles (strict booleans, extra="forbid") so a string
    like "false" or an unknown/typo key raises ValidationError instead of silently
    coercing to the wrong value — the caller is expected to handle that loudly rather
    than leave positions mis-managed. The input `config` is never mutated.
    """
    if toggles is None:
        return config.model_copy()

    if not isinstance(toggles, AIManagerCapabilityToggles):
        if not isinstance(toggles, dict):
            raise TypeError(
                f"ai_manager_capabilities must be a mapping or AIManagerCapabilityToggles, "
                f"got {type(toggles).__name__}"
            )
        # Validate dicts via the model. This raises ValidationError on bad keys or
        # value-types (e.g. a non-bool string that isn't a recognized boolean) —
        # fail loud, not silent.
        toggles = AIManagerCapabilityToggles(**toggles)

    toggle_values = toggles.model_dump()
    updates = {
        CAPABILITY_FLAG_MAP[key]: toggle_values[key]
        for key in CAPABILITY_FLAG_MAP
    }
    return config.model_copy(update=updates)
