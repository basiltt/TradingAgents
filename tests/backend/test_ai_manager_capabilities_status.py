"""Tests for the AI Manager dashboard capability registry (CapabilitiesStatusAggregator).

Guards the WF-3 fix: every registry config_flag must be a real AIManagerConfig field,
the sweep card must map to sweep_defense_enabled (not orderbook), and a per-scan
override of a capability flag must be reflected in the dashboard status.
"""
from __future__ import annotations

from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_capabilities_status import (
    CAPABILITY_REGISTRY,
    CapabilitiesStatusAggregator,
)


def _aggregator(config: dict) -> CapabilitiesStatusAggregator:
    return CapabilitiesStatusAggregator(
        config=config,
        degradation_tier=1,
        task_state={},
        evaluation_interval_s=60,
        next_eval_at=None,
    )


def test_every_registry_config_flag_is_real_aimanager_field():
    """A typo'd config_flag would silently report a capability as always-on."""
    fields = set(AIManagerConfig.model_fields.keys())
    for cap in CAPABILITY_REGISTRY:
        flag = cap["config_flag"]
        if flag is not None:
            assert flag in fields, f"{cap['key']} -> {flag} is not an AIManagerConfig field"


def test_sweep_card_maps_to_sweep_defense_not_orderbook():
    """WF-3: disabling sweep_defense must show the sweep card as disabled, even with
    orderbook still on (the old bug mapped sweep_detection -> orderbook_enabled)."""
    sweep = next(c for c in CAPABILITY_REGISTRY if c["key"] == "sweep_detection")
    assert sweep["config_flag"] == "sweep_defense_enabled"

    config = AIManagerConfig(orderbook_enabled=True, sweep_defense_enabled=False).model_dump()
    rows = {r["capability_key"]: r for r in _aggregator(config).get_capabilities()}
    assert rows["sweep_detection"]["enabled"] is False
    assert rows["sweep_detection"]["status"] == "disabled"
    # orderbook itself stays enabled — the two are now independent
    assert rows["orderbook"]["enabled"] is True


def test_safety_capabilities_have_cards():
    """emergency_close / trailing / event_driven / regime must be visible so a
    per-scan override of them isn't invisible on the dashboard."""
    keys = {c["key"] for c in CAPABILITY_REGISTRY}
    assert {"emergency_close", "trailing", "event_driven", "regime_detection"} <= keys


def test_emergency_close_override_reflected_as_disabled():
    config = AIManagerConfig(emergency_close_enabled=False).model_dump()
    rows = {r["capability_key"]: r for r in _aggregator(config).get_capabilities()}
    assert rows["emergency_close"]["enabled"] is False
    assert rows["emergency_close"]["status"] == "disabled"


def test_regime_card_reflects_regime_enhanced_flag():
    on = {r["capability_key"]: r for r in _aggregator(
        AIManagerConfig(regime_enhanced=True).model_dump()).get_capabilities()}
    off = {r["capability_key"]: r for r in _aggregator(
        AIManagerConfig(regime_enhanced=False).model_dump()).get_capabilities()}
    assert on["regime_detection"]["enabled"] is True
    assert off["regime_detection"]["enabled"] is False
