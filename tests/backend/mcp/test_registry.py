"""Tests for the MCP tool registry — TASK-P0-04.

RED-first: these define the registry contract (ToolGroup/SafetyClass enums, the
@tool decorator, resolve_enabled, preset predicates, tier ordering, deny-list).
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel


class _In(BaseModel):
    x: int = 0


class _Out(BaseModel):
    y: int = 0


@pytest.fixture(autouse=True)
def _clear_registry():
    """Each test starts with an empty registry."""
    from backend.mcp.core import registry

    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


def test_tool_group_and_safety_class_enums():
    from backend.mcp.core.registry import SafetyClass, ToolGroup

    assert ToolGroup.SCANS
    assert ToolGroup.OPTIMIZER
    assert ToolGroup.ADVANCED
    assert SafetyClass.READ_ONLY
    assert SafetyClass.BACKTEST
    assert SafetyClass.LIVE_MONEY


def test_tool_decorator_registers_with_docstring_description():
    from backend.mcp.core.registry import SafetyClass, ToolGroup, _REGISTRY, tool

    @tool(
        name="scans_list",
        group=ToolGroup.SCANS,
        input_schema=_In,
        output_schema=_Out,
        safety_class=SafetyClass.READ_ONLY,
    )
    async def handler(args, ctx):
        """List scans."""
        return _Out()

    assert "scans_list" in _REGISTRY
    spec = _REGISTRY["scans_list"]
    assert spec.group is ToolGroup.SCANS
    assert spec.safety_class is SafetyClass.READ_ONLY
    assert spec.mutating is False
    assert spec.description == "List scans."
    # the decorator returns the handler unchanged
    assert handler.__name__ == "handler"


def test_tool_name_regex_rejects_bad_names():
    from backend.mcp.core.registry import SafetyClass, ToolGroup, tool

    with pytest.raises(ValueError):

        @tool(
            name="BadName",
            group=ToolGroup.SCANS,
            input_schema=_In,
            output_schema=_Out,
            safety_class=SafetyClass.READ_ONLY,
        )
        async def h(args, ctx):
            """d."""


def test_tool_duplicate_name_rejected():
    from backend.mcp.core.registry import SafetyClass, ToolGroup, tool

    @tool(name="scans_list", group=ToolGroup.SCANS, input_schema=_In,
          output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
    async def h1(args, ctx):
        """d."""

    with pytest.raises(ValueError):

        @tool(name="scans_list", group=ToolGroup.SCANS, input_schema=_In,
              output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
        async def h2(args, ctx):
            """d."""


def test_tool_empty_docstring_rejected():
    from backend.mcp.core.registry import SafetyClass, ToolGroup, tool

    with pytest.raises(ValueError):

        @tool(name="scans_get", group=ToolGroup.SCANS, input_schema=_In,
              output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
        async def h(args, ctx):
            pass  # no docstring


def test_tier_allows_ordering():
    from backend.mcp.core.registry import SafetyClass, tier_allows

    # READ_ONLY tool allowed at every tier
    assert tier_allows(SafetyClass.READ_ONLY, "READ_ONLY")
    assert tier_allows(SafetyClass.READ_ONLY, "BACKTEST")
    assert tier_allows(SafetyClass.READ_ONLY, "LIVE_MONEY")
    # BACKTEST tool denied at READ_ONLY tier, allowed at BACKTEST+
    assert not tier_allows(SafetyClass.BACKTEST, "READ_ONLY")
    assert tier_allows(SafetyClass.BACKTEST, "BACKTEST")
    # LIVE_MONEY tool only at LIVE_MONEY tier
    assert not tier_allows(SafetyClass.LIVE_MONEY, "BACKTEST")
    assert tier_allows(SafetyClass.LIVE_MONEY, "LIVE_MONEY")


def test_resolve_enabled_most_restrictive():
    from backend.mcp.core.registry import (
        MCPConfigView, SafetyClass, ToolGroup, resolve_enabled, tool,
    )

    @tool(name="scans_list", group=ToolGroup.SCANS, input_schema=_In,
          output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
    async def h1(args, ctx):
        """d."""

    @tool(name="accounts_list", group=ToolGroup.ACCOUNTS, input_schema=_In,
          output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
    async def h2(args, ctx):
        """d."""

    # group SCANS enabled, tier READ_ONLY -> only scans_list
    cfg = MCPConfigView(
        capability_tier="READ_ONLY",
        enabled_groups=["scans"],
        enabled_tools={},
    )
    names = {s.name for s in resolve_enabled(cfg, available=lambda g: True)}
    assert names == {"scans_list"}

    # individual tool disable wins over enabled group
    cfg2 = MCPConfigView(
        capability_tier="READ_ONLY",
        enabled_groups=["scans", "accounts"],
        enabled_tools={"accounts_list": False},
    )
    names2 = {s.name for s in resolve_enabled(cfg2, available=lambda g: True)}
    assert names2 == {"scans_list"}


def test_resolve_enabled_excludes_when_service_absent():
    from backend.mcp.core.registry import (
        MCPConfigView, SafetyClass, ToolGroup, resolve_enabled, tool,
    )

    @tool(name="scans_list", group=ToolGroup.SCANS, input_schema=_In,
          output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
    async def h1(args, ctx):
        """d."""

    cfg = MCPConfigView(capability_tier="READ_ONLY", enabled_groups=["scans"], enabled_tools={})
    # backing service unavailable -> tool excluded
    names = {s.name for s in resolve_enabled(cfg, available=lambda g: False)}
    assert names == set()


def test_minimal_preset_is_read_only_and_excludes_mutating():
    from backend.mcp.core.registry import (
        PRESETS, SafetyClass, ToolGroup, tool,
    )

    @tool(name="scans_list", group=ToolGroup.SCANS, input_schema=_In,
          output_schema=_Out, safety_class=SafetyClass.READ_ONLY)
    async def h1(args, ctx):
        """d."""

    @tool(name="backtest_run", group=ToolGroup.BACKTEST, input_schema=_In,
          output_schema=_Out, safety_class=SafetyClass.BACKTEST, mutating=True)
    async def h2(args, ctx):
        """d."""

    from backend.mcp.core.registry import _REGISTRY

    minimal = PRESETS["minimal"]
    selected = {n for n, s in _REGISTRY.items() if minimal(s)}
    assert "scans_list" in selected
    assert "backtest_run" not in selected  # mutating/backtest excluded from minimal
