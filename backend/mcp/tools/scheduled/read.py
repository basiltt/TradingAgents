"""Scheduled-scan + strategy + scans_get read tools — TASK-P1-01/07/08."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.redact import strip_secret_keys
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool


class EmptyIn(BaseModel):
    """No-argument tool input."""


# --- scans_get (SCANS) ---

class ScansGetIn(BaseModel):
    scan_id: str = Field(min_length=1, max_length=128)


class ScansGetOut(BaseModel):
    scan: Optional[dict[str, Any]]
    results: list[dict[str, Any]] = []


@tool(
    name="scans_get",
    group=ToolGroup.SCANS,
    input_schema=ScansGetIn,
    output_schema=ScansGetOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def scans_get(args: ScansGetIn, ctx: Any) -> ScansGetOut:
    """Get a stored scan and its ranked results WITHOUT re-running the scanner."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("scan storage unavailable")
    scan = await db.get_scan(args.scan_id)
    results: list[dict[str, Any]] = []
    if scan is not None and hasattr(db, "get_scan_results"):
        try:
            results = await db.get_scan_results(args.scan_id)
        except Exception:
            results = []
    return ScansGetOut(
        scan=strip_secret_keys(scan) if scan else None,
        results=[strip_secret_keys(r) for r in (results or [])][:100],
    )


# --- scheduled_list / scheduled_get (SCHEDULED) ---

class ScheduledListOut(BaseModel):
    schedules: list[dict[str, Any]]
    count: int


@tool(
    name="scheduled_list",
    group=ToolGroup.SCHEDULED,
    input_schema=EmptyIn,
    output_schema=ScheduledListOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def scheduled_list(args: EmptyIn, ctx: Any) -> ScheduledListOut:
    """List scheduled scan jobs (schedule, config, last/next run) — secrets stripped."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("schedule storage unavailable")
    rows = await db.list_scheduled_scans()
    cleaned = [strip_secret_keys(r) for r in rows]
    return ScheduledListOut(schedules=cleaned, count=len(cleaned))


# --- strategies_list (STRATEGIES) ---

class StrategiesListOut(BaseModel):
    strategies: list[dict[str, Any]]
    count: int


@tool(
    name="strategies_list",
    group=ToolGroup.STRATEGIES,
    input_schema=EmptyIn,
    output_schema=StrategiesListOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def strategies_list(args: EmptyIn, ctx: Any) -> StrategiesListOut:
    """List reusable strategy definitions (the agent's view of saved playbooks)."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("strategy storage unavailable")
    rows = await db.list_strategies()
    cleaned = [strip_secret_keys(r) for r in rows]
    return StrategiesListOut(strategies=cleaned, count=len(cleaned))
