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


class ScheduledGetIn(BaseModel):
    schedule_id: str = Field(min_length=1, max_length=128)


class ScheduledGetOut(BaseModel):
    schedule: Optional[dict[str, Any]]


@tool(
    name="scheduled_get",
    group=ToolGroup.SCHEDULED,
    input_schema=ScheduledGetIn,
    output_schema=ScheduledGetOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def scheduled_get(args: ScheduledGetIn, ctx: Any) -> ScheduledGetOut:
    """Get one scheduled scan job by id, including its auto_trade_configs (secrets stripped)."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("schedule storage unavailable")
    row = await db.get_scheduled_scan(args.schedule_id)
    return ScheduledGetOut(schedule=strip_secret_keys(row) if row else None)


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


# --- config_current (STRATEGIES) — the live AutoTradeConfig(s) the optimizer targets ---

class ConfigCurrentOut(BaseModel):
    configs: list[dict[str, Any]]
    count: int


@tool(
    name="config_current",
    group=ToolGroup.STRATEGIES,
    input_schema=EmptyIn,
    output_schema=ConfigCurrentOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def config_current(args: EmptyIn, ctx: Any) -> ConfigCurrentOut:
    """List the live auto-trade configs across active scheduled scans (with schedule id + index) — the baseline the optimizer proposes against. Secrets stripped."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("schedule storage unavailable")
    rows = await db.list_scheduled_scans()
    out: list[dict[str, Any]] = []
    for row in rows:
        clean = strip_secret_keys(row)
        scan_config = clean.get("scan_config") or {}
        if isinstance(scan_config, dict):
            configs = scan_config.get("auto_trade_configs") or []
            for idx, cfg in enumerate(configs):
                out.append(
                    {
                        "schedule_id": clean.get("id"),
                        "schedule_name": clean.get("name"),
                        "config_index": idx,
                        "config": cfg,
                    }
                )
    return ConfigCurrentOut(configs=out, count=len(out))
