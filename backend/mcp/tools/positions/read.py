"""Positions read tools — TASK-P1-03 (opaque ids, redacted P&L)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.redact import redact_records
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool

_SUMMARY = ("symbol", "side", "size", "leverage", "unrealised_pnl_pct", "entry_price")


class PositionsListIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    detail: bool = False
    financial_detail: bool = False


class PositionsListOut(BaseModel):
    positions: list[dict[str, Any]]
    count: int


@tool(
    name="positions_list",
    group=ToolGroup.POSITIONS,
    input_schema=PositionsListIn,
    output_schema=PositionsListOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def positions_list(args: PositionsListIn, ctx: Any) -> PositionsListOut:
    """List open positions for an account (symbol, side, size, leverage); absolute P&L redacted to ratios by default."""
    svc = ctx.services.accounts_service
    if svc is None:
        raise MCPServiceUnavailableError("accounts service unavailable")
    rows = await svc.get_positions(args.account_id)
    if not args.detail:
        rows = [{k: r[k] for k in _SUMMARY if k in r} for r in rows]
    redacted = redact_records(rows, allow_financial_detail=args.financial_detail)
    return PositionsListOut(positions=redacted, count=len(redacted))


class PositionGetIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=32)
    financial_detail: bool = False


class PositionGetOut(BaseModel):
    position: Optional[dict[str, Any]]


@tool(
    name="positions_get",
    group=ToolGroup.POSITIONS,
    input_schema=PositionGetIn,
    output_schema=PositionGetOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def positions_get(args: PositionGetIn, ctx: Any) -> PositionGetOut:
    """Get one open position by symbol for an account (absolute P&L redacted by default)."""
    svc = ctx.services.accounts_service
    if svc is None:
        raise MCPServiceUnavailableError("accounts service unavailable")
    rows = await svc.get_positions(args.account_id)
    match = next((r for r in rows if str(r.get("symbol")) == args.symbol), None)
    if match is None:
        return PositionGetOut(position=None)
    redacted = redact_records([match], allow_financial_detail=args.financial_detail)
    return PositionGetOut(position=redacted[0])
