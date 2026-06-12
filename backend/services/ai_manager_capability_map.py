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
    through AIManagerCapabilityToggles (extra="forbid"): unknown/typo keys and
    non-coercible values raise ValidationError, while ordinary boolean coercion still
    applies (e.g. the JSON string "false" becomes False — the user's intent — rather
    than Python's bool("false")==True footgun). A non-mapping raises TypeError. The
    caller is expected to handle those errors loudly rather than leave positions
    mis-managed. The input `config` is never mutated (only the 8 capability flags are
    changed; auto_enabled and all other fields are preserved by model_copy).
    """
    if toggles is None:
        return config.model_copy()

    if not isinstance(toggles, AIManagerCapabilityToggles):
        if not isinstance(toggles, dict):
            raise TypeError(
                f"ai_manager_capabilities must be a mapping or AIManagerCapabilityToggles, "
                f"got {type(toggles).__name__}"
            )
        # Validate dicts via the model (extra="forbid" rejects unknown keys; bad
        # value-types raise) — fail loud, not silent.
        toggles = AIManagerCapabilityToggles(**toggles)

    toggle_values = toggles.model_dump()
    updates = {
        CAPABILITY_FLAG_MAP[key]: toggle_values[key]
        for key in CAPABILITY_FLAG_MAP
    }
    return config.model_copy(update=updates)


def extract_capability_toggles(config: AIManagerConfig) -> dict[str, bool]:
    """Return the 8 capability toggles read back off an AIManagerConfig.

    Inverse of apply_capability_overrides. Used to persist only the per-scan
    capability selection (8 bools) — never the whole config — so that re-applying it
    onto a freshly-loaded config picks up current values for everything else
    (locked_positions, patched limits, ...) rather than resurrecting a stale snapshot.
    """
    return {
        toggle_key: bool(getattr(config, flag_name))
        for toggle_key, flag_name in CAPABILITY_FLAG_MAP.items()
    }
