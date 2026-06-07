"""Tests for the dispatch pipeline + error mapping — TASK-P0-06."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from backend.mcp.core.registry import SafetyClass, ToolGroup


class _In(BaseModel):
    x: int = 1


class _Out(BaseModel):
    y: int


@pytest.fixture
def ctx():
    from backend.mcp.core.dispatch import CallContext
    from backend.mcp.core.clock import RealClock

    return CallContext(
        principal="tok123",
        session_id="sess1",
        tier="READ_ONLY",
        correlation_id=None,
        services=object(),
        clock=RealClock(),
    )


@pytest.mark.asyncio
async def test_dispatch_calls_handler_and_shapes_result(ctx):
    from backend.mcp.core.dispatch import dispatch
    from backend.mcp.core.registry import ToolSpec

    async def handler(args, c):
        return _Out(y=args.x + 1)

    spec = ToolSpec(
        name="scans_list", group=ToolGroup.SCANS, handler=handler,
        input_schema=_In, output_schema=_Out, safety_class=SafetyClass.READ_ONLY,
        mutating=False, exchange_facing=False, description="d",
    )
    audited = []
    result = await dispatch(spec, {"x": 4}, ctx, audit=audited.append)
    assert result["isError"] is False
    assert result["structuredContent"] == {"y": 5}
    # exactly one audit record, status ok
    assert len(audited) == 1 and audited[0]["status"] == "ok"
    assert audited[0]["tool_name"] == "scans_list"


@pytest.mark.asyncio
async def test_dispatch_tier_gate_denies_over_tier_tool(ctx):
    from backend.mcp.core.dispatch import dispatch
    from backend.mcp.core.registry import ToolSpec

    async def handler(args, c):
        return _Out(y=1)

    spec = ToolSpec(
        name="backtest_run", group=ToolGroup.BACKTEST, handler=handler,
        input_schema=_In, output_schema=_Out, safety_class=SafetyClass.BACKTEST,
        mutating=True, exchange_facing=False, description="d",
    )
    audited = []
    result = await dispatch(spec, {"x": 1}, ctx, audit=audited.append)  # tier READ_ONLY
    assert result["isError"] is True
    assert "tier" in result["content"][0]["text"].lower() or "denied" in result["content"][0]["text"].lower()
    assert audited[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_dispatch_maps_domain_exception(ctx):
    from backend.mcp.core.dispatch import dispatch
    from backend.mcp.core.errors import MCPNotFoundError
    from backend.mcp.core.registry import ToolSpec

    async def handler(args, c):
        raise MCPNotFoundError("scan 9 not found")

    spec = ToolSpec(
        name="scans_get", group=ToolGroup.SCANS, handler=handler,
        input_schema=_In, output_schema=_Out, safety_class=SafetyClass.READ_ONLY,
        mutating=False, exchange_facing=False, description="d",
    )
    audited = []
    result = await dispatch(spec, {"x": 1}, ctx, audit=audited.append)
    assert result["isError"] is True
    assert "not found" in result["content"][0]["text"].lower()
    assert audited[0]["status"] == "error"


@pytest.mark.asyncio
async def test_dispatch_unmapped_exception_is_generic_internal_error(ctx):
    from backend.mcp.core.dispatch import dispatch
    from backend.mcp.core.registry import ToolSpec

    async def handler(args, c):
        raise RuntimeError("secret-leak boom")

    spec = ToolSpec(
        name="scans_list", group=ToolGroup.SCANS, handler=handler,
        input_schema=_In, output_schema=_Out, safety_class=SafetyClass.READ_ONLY,
        mutating=False, exchange_facing=False, description="d",
    )
    audited = []
    result = await dispatch(spec, {"x": 1}, ctx, audit=audited.append)
    assert result["isError"] is True
    # generic message — must NOT leak the raw exception text
    assert "secret-leak" not in result["content"][0]["text"]
    assert audited[0]["status"] == "error"


@pytest.mark.asyncio
async def test_dispatch_invalid_args_returns_invalid_params(ctx):
    from backend.mcp.core.dispatch import dispatch
    from backend.mcp.core.registry import ToolSpec

    async def handler(args, c):
        return _Out(y=1)

    spec = ToolSpec(
        name="scans_list", group=ToolGroup.SCANS, handler=handler,
        input_schema=_In, output_schema=_Out, safety_class=SafetyClass.READ_ONLY,
        mutating=False, exchange_facing=False, description="d",
    )
    audited = []
    result = await dispatch(spec, {"x": "not-an-int"}, ctx, audit=audited.append)
    assert result["isError"] is True
    assert audited[0]["status"] in ("rejected", "error")
