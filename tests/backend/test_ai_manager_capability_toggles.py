"""Schema tests for per-scan AI Manager capability toggles."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas import AIManagerCapabilityToggles, AutoTradeConfig

ALL_KEYS = {
    "mtf", "orderbook", "sweep_defense", "correlation",
    "regime_enhanced", "event_driven", "trailing", "emergency_close",
}


def test_toggles_default_all_true():
    t = AIManagerCapabilityToggles()
    for key in ALL_KEYS:
        assert getattr(t, key) is True


def test_toggles_partial_object_fills_defaults_true():
    t = AIManagerCapabilityToggles(mtf=False)
    assert t.mtf is False
    assert t.orderbook is True  # omitted key defaults True


def test_toggles_rejects_unknown_key():
    with pytest.raises(ValidationError):
        AIManagerCapabilityToggles(bogus=True)


def test_autotrade_config_capabilities_defaults_none():
    cfg = AutoTradeConfig(account_id="acc_1")
    assert cfg.ai_manager_capabilities is None


def test_autotrade_config_accepts_capabilities_object():
    cfg = AutoTradeConfig(
        account_id="acc_1",
        ai_manager_enabled=True,
        ai_manager_capabilities={"trailing": False},
    )
    assert cfg.ai_manager_capabilities is not None
    assert cfg.ai_manager_capabilities.trailing is False
    assert cfg.ai_manager_capabilities.mtf is True


def test_autotrade_config_capabilities_roundtrip():
    cfg = AutoTradeConfig(
        account_id="acc_1",
        ai_manager_enabled=True,
        ai_manager_capabilities=AIManagerCapabilityToggles(orderbook=False),
    )
    dumped = cfg.model_dump()
    restored = AutoTradeConfig(**dumped)
    assert restored.ai_manager_capabilities.orderbook is False


from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_capability_map import (
    CAPABILITY_FLAG_MAP,
    apply_capability_overrides,
)


def test_flag_map_covers_all_eight_keys():
    assert set(CAPABILITY_FLAG_MAP.keys()) == ALL_KEYS


def test_apply_none_returns_unchanged_copy():
    base = AIManagerConfig()
    out = apply_capability_overrides(base, None)
    assert out.model_dump() == base.model_dump()


def test_apply_overrides_all_flags_off():
    base = AIManagerConfig()
    toggles = AIManagerCapabilityToggles(
        mtf=False, orderbook=False, sweep_defense=False, correlation=False,
        regime_enhanced=False, event_driven=False, trailing=False,
        emergency_close=False,
    )
    out = apply_capability_overrides(base, toggles)
    assert out.mtf_enabled is False
    assert out.orderbook_enabled is False
    assert out.sweep_defense_enabled is False
    assert out.correlation_enabled is False
    assert out.regime_enhanced is False
    assert out.event_driven_enabled is False
    assert out.trailing_enabled is False
    assert out.emergency_close_enabled is False


def test_apply_trailing_true_flips_account_default():
    base = AIManagerConfig()
    assert base.trailing_enabled is False  # account default
    out = apply_capability_overrides(base, AIManagerCapabilityToggles())
    assert out.trailing_enabled is True  # toggle default True wins


def test_apply_does_not_mutate_input():
    base = AIManagerConfig()
    apply_capability_overrides(base, AIManagerCapabilityToggles(mtf=False))
    assert base.mtf_enabled is True  # original untouched


def test_apply_accepts_dict_toggles():
    base = AIManagerConfig()
    out = apply_capability_overrides(base, {"orderbook": False})
    assert out.orderbook_enabled is False
    assert out.mtf_enabled is True  # omitted dict key → default True

