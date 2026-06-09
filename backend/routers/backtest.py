"""Backtest router — REST API for backtest lifecycle, results, and comparison."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from backend.schemas.backtest_schemas import BacktestCreateRequest
from backend.services.backtest_service import (
    BacktestBusyError,
    BacktestConflictError,
    BacktestNotFoundError,
    BacktestRateLimitError,
    BacktestValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backtest"])


def _get_service(request: Request):
    svc = getattr(request.app.state, "backtest_service", None)
    if svc is None:
        raise HTTPException(503, detail="Backtesting feature not available")
    return svc


def _validate_run_id(run_id: str) -> str:
    """Reject a non-UUID run_id with 422 rather than letting asyncpg raise a 500.

    backtest_runs.id is a UUID column; an arbitrary path segment would otherwise
    reach `WHERE id = $1` and trigger an unhandled asyncpg DataError.
    """
    import uuid
    try:
        uuid.UUID(run_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(422, detail="Invalid run_id format (expected a UUID)") from None
    return run_id


def _client_id(request: Request) -> str:
    """Best-effort per-client identity for rate limiting (request IP)."""
    client = request.client
    return client.host if client else "anonymous"


@router.post("/backtest", status_code=201)
async def create_backtest(request: Request, body: BacktestCreateRequest):
    """Create and launch a new backtest run. Returns the run_id (201)."""
    svc = _get_service(request)
    try:
        run_id = await svc.create_backtest(body.model_dump(), client_id=_client_id(request))
    except BacktestRateLimitError as exc:
        raise HTTPException(429, detail=str(exc)) from exc
    except BacktestValidationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except BacktestBusyError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content={"run_id": run_id})


@router.get("/backtest")
async def list_backtests(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List backtest runs (newest first), optionally filtered by status."""
    svc = _get_service(request)
    filters: dict[str, Any] = {"limit": limit}
    if status:
        filters["status"] = status
    runs = await svc.list_backtests(filters)
    return _jsonable(runs)


@router.get("/backtest/compare")
async def compare_backtests(
    request: Request,
    run_ids: list[str] = Query(..., min_length=1),
):
    """Compare 2-4 completed backtest runs side by side."""
    svc = _get_service(request)
    for rid in run_ids:
        _validate_run_id(rid)
    try:
        result = await svc.compare_backtests(run_ids)
    except BacktestNotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except BacktestValidationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _jsonable(result)


@router.get("/backtest/{run_id}")
async def get_backtest(request: Request, run_id: str):
    """Get a single backtest run with its results (404 if not found)."""
    svc = _get_service(request)
    _validate_run_id(run_id)
    result = await svc.get_backtest(run_id)
    if result is None:
        raise HTTPException(404, detail="Backtest run not found")
    return _jsonable(result)


@router.get("/backtest/{run_id}/trades")
async def get_backtest_trades(
    request: Request,
    run_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    sort_by: str = Query("entry_time"),
    side: Optional[str] = Query(None),
    close_reason: Optional[str] = Query(None),
):
    """Paginated, filterable list of a run's simulated trades."""
    svc = _get_service(request)
    _validate_run_id(run_id)
    result = await svc.get_backtest_trades(
        run_id, page=page, limit=limit, sort_by=sort_by,
        side=side, close_reason=close_reason,
    )
    return _jsonable(result)


@router.post("/backtest/{run_id}/cancel")
async def cancel_backtest(request: Request, run_id: str):
    """Cancel a pending/running backtest (404 if missing, 409 if already terminal)."""
    svc = _get_service(request)
    _validate_run_id(run_id)
    try:
        ok = await svc.cancel_backtest(run_id)
    except BacktestConflictError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(404, detail="Backtest run not found")
    return {"cancelled": True, "run_id": run_id}


@router.delete("/backtest/{run_id}", status_code=204)
async def delete_backtest(request: Request, run_id: str):
    """Delete a backtest run (404 if missing, 409 if still running)."""
    svc = _get_service(request)
    _validate_run_id(run_id)
    try:
        ok = await svc.delete_backtest(run_id)
    except BacktestConflictError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(404, detail="Backtest run not found")
    return Response(status_code=204)


@router.get("/backtest-cache/status")
async def cache_status(
    request: Request,
    symbols: list[str] = Query(..., min_length=1, max_length=200),
    interval: str = Query("5m"),
    start: str = Query(...),
    end: str = Query(...),
):
    """Report kline-cache coverage for the requested symbols/range (read-only).

    Available for a future config-form coverage banner showing whether a backtest
    can run immediately or needs a cache warm-up. Not yet wired into the UI —
    backtests currently fill the kline cache lazily at run time.
    """
    svc = _get_service(request)
    from datetime import datetime
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, detail="start/end must be ISO 8601 datetimes") from None
    result = await svc.cache_status(symbols, interval, start_dt, end_dt)
    return result


@router.post("/backtest-cache/warmup", status_code=202)
async def warmup_cache(
    request: Request,
    symbols: list[str] = Query(..., min_length=1, max_length=200),
    interval: str = Query("5m"),
    start: str = Query(...),
    end: str = Query(...),
):
    """Warm the kline cache for the requested symbols/range (fetch missing data).

    Returns 202 with the coverage stats. The frontend can then poll cache-status
    or proceed to create a backtest once coverage is ready.
    """
    svc = _get_service(request)
    from datetime import datetime
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, detail="start/end must be ISO 8601 datetimes") from None
    try:
        stats = await svc.warmup_cache(symbols, interval, start_dt, end_dt)
    except BacktestValidationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return JSONResponse(status_code=202, content=_jsonable(stats))


def _jsonable(obj):
    """Coerce datetimes (and nested structures) to JSON-serializable values."""
    from datetime import datetime

    def walk(v):
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return v

    return walk(obj)
