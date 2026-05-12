"""Trading Cycles API router."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas import (
    CreateCycleRequest,
    CycleDetail,
    CycleResponse,
    CycleTradeResponse,
    DryRunResponse,
    PaginatedCycleList,
)
from backend.services.trading_cycle_engine import (
    AccountNotConfiguredError,
    CycleError,
    CycleNotFoundError,
    CycleNotRunningError,
)

router = APIRouter(prefix="/trading-cycles", tags=["trading-cycles"])

_VALID_STATUSES = {"active", "pending", "placing_trades", "running", "stopping", "completed", "stopped", "failed"}


@router.post("", status_code=201, response_model=CycleResponse)
async def create_cycle(request: Request, body: CreateCycleRequest):
    engine = getattr(request.app.state, "cycle_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Cycle engine not available")
    try:
        result = await engine.start_cycle(body)
        return CycleResponse(**result)
    except AccountNotConfiguredError as e:
        raise HTTPException(status_code=503, detail={"code": e.code, "message": e.safe_message})
    except CycleError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.safe_message})


@router.get("", response_model=PaginatedCycleList)
async def list_cycles(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
):
    engine = getattr(request.app.state, "cycle_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Cycle engine not available")
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status filter: {status}")
    items, total = await engine.list_cycles(offset, limit, status=status)
    return PaginatedCycleList(
        items=[CycleResponse(**c) for c in items],
        total=total, offset=offset, limit=limit,
    )


@router.post("/dry-run", response_model=DryRunResponse)
async def dry_run(request: Request, body: CreateCycleRequest):
    engine = getattr(request.app.state, "cycle_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Cycle engine not available")
    try:
        result = await engine.dry_run(body)
        return DryRunResponse(**result)
    except AccountNotConfiguredError as e:
        raise HTTPException(status_code=503, detail={"code": e.code, "message": e.safe_message})
    except CycleError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.safe_message})


@router.get("/{cycle_id}", response_model=CycleDetail)
async def get_cycle(request: Request, cycle_id: int):
    engine = getattr(request.app.state, "cycle_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Cycle engine not available")
    cycle = await engine.get_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return CycleDetail(**cycle)


@router.post("/{cycle_id}/stop", response_model=CycleResponse)
async def stop_cycle(request: Request, cycle_id: int):
    engine = getattr(request.app.state, "cycle_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Cycle engine not available")
    try:
        result = await engine.stop_cycle(cycle_id)
        return CycleResponse(**result)
    except CycleNotFoundError as e:
        raise HTTPException(status_code=404, detail={"code": e.code, "message": e.safe_message})
    except CycleNotRunningError as e:
        raise HTTPException(status_code=409, detail={"code": e.code, "message": e.safe_message})
