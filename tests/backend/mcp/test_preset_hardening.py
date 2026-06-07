"""Preset hardening tests — defense-in-depth from the P2 security review.

Two guarantees:
1. The broad presets (_standard, _full) must never select an exchange-facing
   tool, even one mislabeled with a non-live-money safety class.
2. apply_preset must never write a capability_tier above BACKTEST, regardless
   of what the preset predicate selects — arming the money path always requires
   the explicit tier control, never a one-click preset.
"""
from __future__ import annotations

import pytest

from backend.mcp.core.registry import (
    _TIER_RANK,
    PRESETS,
    SafetyClass,
    iter_specs,
    required_tier,
)


def test_broad_presets_exclude_exchange_facing():
    """No exchange-facing tool may be selected by _standard or _full."""
    from backend.mcp.discovery import discover_tools

    discover_tools()
    specs = iter_specs()
    for preset_name in ("standard", "full"):
        pred = PRESETS[preset_name]
        for spec in specs:
            if spec.exchange_facing:
                assert not pred(spec), (
                    f"preset {preset_name!r} selected exchange-facing tool {spec.name!r}"
                )


def test_no_preset_selects_live_money():
    """No preset may ever select a LIVE_MONEY-safety tool."""
    from backend.mcp.discovery import discover_tools

    discover_tools()
    specs = iter_specs()
    for preset_name, pred in PRESETS.items():
        for spec in specs:
            if spec.safety_class is SafetyClass.LIVE_MONEY:
                assert not pred(spec), (
                    f"preset {preset_name!r} selected live-money tool {spec.name!r}"
                )


def test_required_tier_of_every_preset_is_at_most_backtest():
    """The tier any preset would write must never exceed BACKTEST."""
    from backend.mcp.discovery import discover_tools

    discover_tools()
    specs = iter_specs()
    backtest_rank = _TIER_RANK["BACKTEST"]
    for preset_name, pred in PRESETS.items():
        selected = [s for s in specs if pred(s)]
        tier = required_tier(selected)
        assert _TIER_RANK[tier] <= backtest_rank, (
            f"preset {preset_name!r} would write tier {tier!r} above BACKTEST"
        )
