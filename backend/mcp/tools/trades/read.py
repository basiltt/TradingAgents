"""Trades read tools — TASK-P1-04 (filters, redacted P&L, paginated)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError, MCPValidationError
from backend.mcp.core.redact import redact_records
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool
from backend.mcp.core.shape import CursorError, decode_cursor, encode_cursor

_SUMMARY = ("id", "symbol", "side", "status", "close_reason", "pnl_pct", "created_at")


class TradesListIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    status: Optional[str] = None
    symbol: Optional[str] = Field(default=None, max_length=32)
    side: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: Optional[str] = None
    detail: bool = False
    financial_detail: bool = False


class TradesListOut(BaseModel):
    trades: list[dict[str, Any]]
    count: int
    next_cursor: Optional[str] = None


@tool(
    name="trades_list",
    group=ToolGroup.TRADES,
    input_schema=TradesListIn,
    output_schema=TradesListOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def trades_list(args: TradesListIn, ctx: Any) -> TradesListOut:
    """List trades for an account with optional status/symbol/side filters; absolute P&L redacted to ratios by default. Cursor-paginated."""
    repo = ctx.services.trade_repo
    db = ctx.services.db
    if repo is None or db is None or getattr(db, "pool", None) is None:
        raise MCPServiceUnavailableError("trade storage unavailable")
    # validate an inbound cursor's shape (opaque + traversal-safe) before use
    raw_cursor: Optional[str] = None
    if args.cursor:
        try:
            _sort_key, raw_cursor = decode_cursor(args.cursor)
        except CursorError as exc:
            raise MCPValidationError(f"invalid cursor: {exc}") from exc
    try:
        async with db.pool.acquire() as conn:
            result = await repo.list_trades(
                conn,
                account_id=args.account_id,
                status=args.status,
                symbol=args.symbol,
                side=args.side,
                cursor=raw_cursor,
                limit=args.limit,
            )
    except ValueError as exc:  # repo raises ValueError on bad filter values
        raise MCPValidationError(str(exc)) from exc

    rows = result.get("trades", result.get("items", [])) if isinstance(result, dict) else result
    repo_cursor = result.get("next_cursor") if isinstance(result, dict) else None
    if not args.detail:
        rows = [{k: r[k] for k in _SUMMARY if k in r} for r in rows]
    redacted = redact_records(rows, allow_financial_detail=args.financial_detail)
    # re-wrap the repo's raw cursor as an opaque token for the agent
    next_cursor = encode_cursor("created_at", str(repo_cursor)) if repo_cursor else None
    return TradesListOut(trades=redacted, count=len(redacted), next_cursor=next_cursor)


class TradeGetIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    trade_id: str = Field(min_length=1, max_length=128)
    financial_detail: bool = False


class TradeGetOut(BaseModel):
    trade: Optional[dict[str, Any]]


@tool(
    name="trades_get",
    group=ToolGroup.TRADES,
    input_schema=TradeGetIn,
    output_schema=TradeGetOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def trades_get(args: TradeGetIn, ctx: Any) -> TradeGetOut:
    """Get one trade by id for an account (absolute P&L redacted by default)."""
    repo = ctx.services.trade_repo
    db = ctx.services.db
    if repo is None or db is None or getattr(db, "pool", None) is None:
        raise MCPServiceUnavailableError("trade storage unavailable")
    async with db.pool.acquire() as conn:
        row = await repo.get_trade(conn, account_id=args.account_id, trade_id=args.trade_id)
    if not row:
        return TradeGetOut(trade=None)
    redacted = redact_records([dict(row)], allow_financial_detail=args.financial_detail)
    return TradeGetOut(trade=redacted[0])
