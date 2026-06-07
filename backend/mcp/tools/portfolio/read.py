"""Portfolio read tool — TASK-P1-05 (aggregated, redacted)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.redact import redact_record
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool

_DAY_MS = 86_400_000


class PortfolioOverviewIn(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    account_type: str | None = None
    financial_detail: bool = False


class PortfolioOverviewOut(BaseModel):
    window_days: int
    summary: dict[str, Any]


@tool(
    name="portfolio_overview",
    group=ToolGroup.PORTFOLIO,
    input_schema=PortfolioOverviewIn,
    output_schema=PortfolioOverviewOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def portfolio_overview(args: PortfolioOverviewIn, ctx: Any) -> PortfolioOverviewOut:
    """Aggregated portfolio P&L summary over a trailing window (win rate, counts); absolute money redacted to ratios by default."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("portfolio storage unavailable")
    now_ms = int(ctx.clock.now().timestamp() * 1000)
    start_ms = now_ms - args.days * _DAY_MS
    summary = await db.get_portfolio_pnl_summary(start_ms, now_ms, account_type=args.account_type)
    redacted = redact_record(dict(summary), allow_financial_detail=args.financial_detail)
    return PortfolioOverviewOut(window_days=args.days, summary=redacted)
