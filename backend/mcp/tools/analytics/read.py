"""Analytics read tools — TASK-P1-06 (performance + signal analytics)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.redact import redact_record
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool


class AnalyticsSummaryIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    days: int = Field(default=30, ge=1, le=365)
    financial_detail: bool = False


class AnalyticsSummaryOut(BaseModel):
    account_id: str
    window_days: int
    analytics: dict[str, Any]


@tool(
    name="analytics_summary",
    group=ToolGroup.ANALYTICS,
    input_schema=AnalyticsSummaryIn,
    output_schema=AnalyticsSummaryOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def analytics_summary(args: AnalyticsSummaryIn, ctx: Any) -> AnalyticsSummaryOut:
    """Performance analytics for one account over a trailing window (Sharpe, Sortino, drawdown, win rate); absolute money redacted by default."""
    svc = ctx.services.accounts_service
    if svc is None:
        raise MCPServiceUnavailableError("accounts service unavailable")
    end = ctx.clock.now().date()
    start = end - timedelta(days=args.days)
    data = await svc.compute_analytics(args.account_id, start.isoformat(), end.isoformat())
    redacted = redact_record(dict(data), allow_financial_detail=args.financial_detail)
    return AnalyticsSummaryOut(account_id=args.account_id, window_days=args.days, analytics=redacted)


class SignalAnalyticsIn(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class SignalAnalyticsOut(BaseModel):
    window_days: int
    analytics: dict[str, Any]


@tool(
    name="signal_analytics",
    group=ToolGroup.ANALYTICS,
    input_schema=SignalAnalyticsIn,
    output_schema=SignalAnalyticsOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def signal_analytics(args: SignalAnalyticsIn, ctx: Any) -> SignalAnalyticsOut:
    """Aggregated signal-quality analytics (total trades, win rate, avg P&L) over a trailing window."""
    svc = ctx.services.signal_analytics_service
    if svc is None:
        raise MCPServiceUnavailableError("signal analytics service unavailable")
    end = ctx.clock.now().date()
    start = end - timedelta(days=args.days)
    data = await svc.get_summary(start_date=start.isoformat(), end_date=end.isoformat())
    return SignalAnalyticsOut(window_days=args.days, analytics=dict(data) if data else {})
