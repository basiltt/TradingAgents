"""Backtest tools — TASK-P3-01/02 (BACKTEST tier).

`backtest_run` reuses the app's BacktestCreateRequest as its input schema so the
advertised contract equals the live validation (schema-equivalence). Backtests
are background tasks; backtest_get is the fire-and-poll handle.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import (
    MCPRateLimitError,
    MCPServiceUnavailableError,
    MCPValidationError,
)
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool
from backend.schemas.backtest_schemas import BacktestCreateRequest


class BacktestRunOut(BaseModel):
    run_id: str


@tool(
    name="backtest_run",
    group=ToolGroup.BACKTEST,
    input_schema=BacktestCreateRequest,
    output_schema=BacktestRunOut,
    safety_class=SafetyClass.BACKTEST,
    mutating=True,
)
async def backtest_run(args: BacktestCreateRequest, ctx: Any) -> BacktestRunOut:
    """Create + launch a backtest over historical scans with a given AutoTradeConfig."""
    svc = ctx.services.backtest_service
    if svc is None:
        raise MCPServiceUnavailableError("backtest service unavailable")
    from backend.services.backtest_service import (
        BacktestBusyError,
        BacktestRateLimitError,
        BacktestValidationError,
    )

    try:
        run_id = await svc.create_backtest(args.model_dump(), client_id=f"mcp:{ctx.principal}")
    except BacktestRateLimitError as exc:
        raise MCPRateLimitError(str(exc)) from exc
    except BacktestBusyError as exc:
        raise MCPRateLimitError(str(exc)) from exc
    except BacktestValidationError as exc:
        raise MCPValidationError(str(exc)) from exc
    return BacktestRunOut(run_id=run_id)


class BacktestGetIn(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)


class BacktestGetOut(BaseModel):
    run: Optional[dict[str, Any]]


@tool(
    name="backtest_get",
    group=ToolGroup.BACKTEST,
    input_schema=BacktestGetIn,
    output_schema=BacktestGetOut,
    safety_class=SafetyClass.BACKTEST,
)
async def backtest_get(args: BacktestGetIn, ctx: Any) -> BacktestGetOut:
    """Get a backtest run (status -> results). The fire-and-poll handle."""
    svc = ctx.services.backtest_service
    if svc is None:
        raise MCPServiceUnavailableError("backtest service unavailable")
    run = await svc.get_backtest(args.run_id)
    return BacktestGetOut(run=run)


class BacktestListIn(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    status: Optional[str] = None


class BacktestListOut(BaseModel):
    runs: list[dict[str, Any]]
    count: int


@tool(
    name="backtest_list",
    group=ToolGroup.BACKTEST,
    input_schema=BacktestListIn,
    output_schema=BacktestListOut,
    safety_class=SafetyClass.BACKTEST,
)
async def backtest_list(args: BacktestListIn, ctx: Any) -> BacktestListOut:
    """List backtest runs (newest first), optionally filtered by status."""
    svc = ctx.services.backtest_service
    if svc is None:
        raise MCPServiceUnavailableError("backtest service unavailable")
    filters: dict[str, Any] = {"limit": args.limit}
    if args.status:
        filters["status"] = args.status
    runs = await svc.list_backtests(filters)
    return BacktestListOut(runs=runs, count=len(runs))


class BacktestCompareIn(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=4)


class BacktestCompareOut(BaseModel):
    comparison: dict[str, Any]


@tool(
    name="backtest_compare",
    group=ToolGroup.BACKTEST,
    input_schema=BacktestCompareIn,
    output_schema=BacktestCompareOut,
    safety_class=SafetyClass.BACKTEST,
)
async def backtest_compare(args: BacktestCompareIn, ctx: Any) -> BacktestCompareOut:
    """Compare 2-4 completed backtest runs on the standard metric set."""
    svc = ctx.services.backtest_service
    if svc is None:
        raise MCPServiceUnavailableError("backtest service unavailable")
    result = await svc.compare_backtests(args.run_ids)
    return BacktestCompareOut(comparison=result)
