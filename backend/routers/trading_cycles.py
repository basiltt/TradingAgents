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
    engine = _get_engine(request)
    try:
        result = await engine.start_cycle(body)
        return CycleResponse(**result)
    except AccountNotConfiguredError as e:
        raise HTTPException(503, detail=e.safe_message)
    except CycleError as e:
        raise HTTPException(400, detail=e.safe_message)


@router.get("/trading-cycles")
async def list_cycles(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
):
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
    engine = _get_engine(request)
    try:
        result = await engine.dry_run(body)
        return DryRunResponse(**result)
    except AccountNotConfiguredError as e:
        raise HTTPException(503, detail=e.safe_message)
    except CycleError as e:
        raise HTTPException(400, detail=e.safe_message)


@router.get("/trading-cycles/{cycle_id}")
async def get_cycle(request: Request, cycle_id: int):
    engine = _get_engine(request)
    cycle = await engine.get_cycle(cycle_id)
    if not cycle:
        raise HTTPException(404, detail="Cycle not found")
    return CycleDetail(**cycle)


@router.post("/trading-cycles/{cycle_id}/stop")
async def stop_cycle(request: Request, cycle_id: int):
    engine = _get_engine(request)
    try:
        result = await engine.stop_cycle(cycle_id)
        return CycleResponse(**result)
    except CycleNotFoundError:
        raise HTTPException(404, detail="Cycle not found")
    except CycleNotRunningError:
        raise HTTPException(409, detail="Cycle is not running")
