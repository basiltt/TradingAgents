"""Trading Cycles API router."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas import (
    CreateCycleRequest,
    CycleDetail,
    CycleResponse,
    DryRunResponse,
    PaginatedCycleList,
)
from backend.services.trading_cycle_engine import (
    AccountNotConfiguredError,
    CycleError,
    CycleNotFoundError,
    CycleNotRunningError,
)

router = APIRouter(tags=["trading-cycles"])

_VALID_STATUSES = {"active", "pending", "placing_trades", "running", "stopping", "completed", "stopped", "failed"}


def _get_engine(request: Request):
    engine = getattr(request.app.state, "cycle_engine", None)
    if engine is None:
        raise HTTPException(503, detail="Cycle engine not available")
    return engine


@router.post("/trading-cycles", status_code=201)
async def create_cycle(request: Request, body: CreateCycleRequest):
    """Start a new trading cycle from a scan; returns the created cycle (201).

    503 if the account is not configured, 400 on other cycle errors.
    """
    engine = _get_engine(request)
    try:
        result = await engine.start_cycle(body)
        return CycleResponse(**result)
    except AccountNotConfiguredError as e:
        raise HTTPException(503, detail=e.safe_message) from e
    except CycleError as e:
        raise HTTPException(400, detail=e.safe_message) from e


@router.get("/trading-cycles")
async def list_cycles(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
):
    """List trading cycles with pagination and an optional status filter.

    400 if status is not a recognized value. Returns a paginated cycle list.
    """
    engine = _get_engine(request)
    if status and status not in _VALID_STATUSES:
        raise HTTPException(400, detail=f"Invalid status filter: {status}")
    items, total = await engine.list_cycles(offset, limit, status=status)
    return PaginatedCycleList(
        items=[CycleResponse(**c) for c in items],
        total=total, offset=offset, limit=limit,
    )


@router.post("/trading-cycles/dry-run")
async def dry_run(request: Request, body: CreateCycleRequest):
    """Preview a trading cycle without placing trades.

    503 if the account is not configured, 400 on other cycle errors. Returns
    the projected dry-run result.
    """
    engine = _get_engine(request)
    try:
        result = await engine.dry_run(body)
        return DryRunResponse(**result)
    except AccountNotConfiguredError as e:
        raise HTTPException(503, detail=e.safe_message) from e
    except CycleError as e:
        raise HTTPException(400, detail=e.safe_message) from e


@router.get("/trading-cycles/{cycle_id}")
async def get_cycle(request: Request, cycle_id: int):
    """Get full detail for one trading cycle by id; 404 if not found."""
    engine = _get_engine(request)
    cycle = await engine.get_cycle(cycle_id)
    if not cycle:
        raise HTTPException(404, detail="Cycle not found")
    return CycleDetail(**cycle)


@router.post("/trading-cycles/{cycle_id}/stop")
async def stop_cycle(request: Request, cycle_id: int):
    """Stop a running trading cycle; 404 if not found, 409 if not running."""
    engine = _get_engine(request)
    try:
        result = await engine.stop_cycle(cycle_id)
        return CycleResponse(**result)
    except CycleNotFoundError:
        raise HTTPException(404, detail="Cycle not found") from None
    except CycleNotRunningError:
        raise HTTPException(409, detail="Cycle is not running") from None
