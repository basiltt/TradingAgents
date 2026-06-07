"""scans_list read tool — TASK-P0-13.

Lists recent scans from the DB without invoking the scanner (side-effect-free).
Compact summary projection. The reference read tool for the P0 walking skeleton.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool


class ScansListIn(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)


class ScanSummary(BaseModel):
    scan_id: str
    status: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    started_at: Optional[str] = None


class ScansListOut(BaseModel):
    scans: list[ScanSummary]
    count: int


@tool(
    name="scans_list",
    group=ToolGroup.SCANS,
    input_schema=ScansListIn,
    output_schema=ScansListOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def scans_list(args: ScansListIn, ctx: Any) -> ScansListOut:
    """List recent market scans (id, status, counts) without re-running them."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("scan storage unavailable")
    rows = await db.list_scans()
    summaries: list[ScanSummary] = []
    for r in rows[: args.limit]:
        started = r.get("started_at")
        summaries.append(
            ScanSummary(
                scan_id=str(r.get("scan_id")),
                status=str(r.get("status", "unknown")),
                total=int(r.get("total") or 0),
                completed=int(r.get("completed") or 0),
                failed=int(r.get("failed") or 0),
                started_at=started.isoformat() if hasattr(started, "isoformat") else (str(started) if started else None),
            )
        )
    return ScansListOut(scans=summaries, count=len(summaries))
