"""Debug forensics read tools — TASK-P3-04 (gated by allow_debug, redacted)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.redact import strip_secret_keys
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool

_MAX_TREE = 5000  # depth/size cap on returned trace trees


def _cap(obj: Any, *, budget: int = _MAX_TREE) -> Any:
    """Recursively cap a trace structure's size; strip credential-shaped keys."""
    if isinstance(obj, dict):
        return {k: _cap(v, budget=budget) for k, v in strip_secret_keys(obj).items()}
    if isinstance(obj, list):
        return [_cap(v, budget=budget) for v in obj[:budget]]
    return obj


class DebugScanIn(BaseModel):
    scan_id: str = Field(min_length=1, max_length=128)


class DebugScanOut(BaseModel):
    tree: Optional[dict[str, Any]]


@tool(
    name="debug_scan_trace",
    group=ToolGroup.DEBUG,
    input_schema=DebugScanIn,
    output_schema=DebugScanOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def debug_scan_trace(args: DebugScanIn, ctx: Any) -> DebugScanOut:
    """Read the auto-trade decision trace for a scan (forensics; redacted, capped)."""
    recorder = ctx.services.debug_trace_recorder
    repo = getattr(recorder, "repo", None) if recorder is not None else None
    if repo is None:
        raise MCPServiceUnavailableError("debug tracing not available")
    rid = await repo.get_latest_run_id_for_scan(args.scan_id)
    if rid is None:
        return DebugScanOut(tree=None)
    tree = await repo.get_run_tree(rid)
    return DebugScanOut(tree=_cap(tree) if tree else None)


class DebugSymbolIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    scan_id: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=500)


class DebugSymbolOut(BaseModel):
    items: list[dict[str, Any]]


@tool(
    name="debug_symbol_decisions",
    group=ToolGroup.DEBUG,
    input_schema=DebugSymbolIn,
    output_schema=DebugSymbolOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def debug_symbol_decisions(args: DebugSymbolIn, ctx: Any) -> DebugSymbolOut:
    """Read per-symbol auto-trade decisions across scans (redacted)."""
    recorder = ctx.services.debug_trace_recorder
    repo = getattr(recorder, "repo", None) if recorder is not None else None
    if repo is None:
        raise MCPServiceUnavailableError("debug tracing not available")
    items = await repo.get_symbol_decisions(args.symbol, scan_id=args.scan_id, limit=args.limit)
    return DebugSymbolOut(items=[strip_secret_keys(i) for i in (items or [])])
