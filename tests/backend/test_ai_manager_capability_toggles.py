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
