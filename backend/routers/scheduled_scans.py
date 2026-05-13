"""Scheduled scans router — CRUD + control for scan schedules."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import (
    CreateScheduledScanRequest,
    ScheduledScanResponse,
    ScheduleExecutionResponse,
    UpdateScheduledScanRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scheduled-scans"])


def _validate_uuid(value: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")


def _get_service(request: Request):
    svc = getattr(request.app.state, "scheduler_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Scheduled scans service not available")
    return svc


def _redact_response(data: dict) -> ScheduledScanResponse:
    sc = data.get("scan_config")
    if isinstance(sc, dict) and "llm_api_key" in sc:
        sc = {**sc, "llm_api_key": "***"}
        data = {**data, "scan_config": sc}
    return ScheduledScanResponse(**data)


@router.post("/scheduled-scans", status_code=201)
async def create_schedule(request: Request, body: CreateScheduledScanRequest):
    svc = _get_service(request)
    try:
        result = await svc.create(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _redact_response(result)


@router.get("/scheduled-scans")
async def list_schedules(request: Request):
    svc = _get_service(request)
    schedules = await svc.list_all()
    running_ids = svc.get_running_schedule_ids()
    results = []
    for s in schedules:
        resp = _redact_response(s)
        if s.get("id") in running_ids:
            resp.is_running = True
        results.append(resp)
    return {"schedules": results}


@router.get("/scheduled-scans/{schedule_id}")
async def get_schedule(request: Request, schedule_id: str):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    schedule = await svc.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    executions = await svc.list_executions(schedule_id, limit=5)
    resp = _redact_response(schedule)
    if schedule.get("id") in svc.get_running_schedule_ids():
        resp.is_running = True
    return {
        **resp.model_dump(),
        "recent_executions": [ScheduleExecutionResponse(**e) for e in executions],
    }


@router.patch("/scheduled-scans/{schedule_id}")
async def update_schedule(request: Request, schedule_id: str, body: UpdateScheduledScanRequest):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    try:
        result = await svc.update(schedule_id, body.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(status_code=404, detail="Schedule not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _redact_response(result)


@router.delete("/scheduled-scans/{schedule_id}")
async def delete_schedule(request: Request, schedule_id: str):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    deleted = await svc.delete(schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": True}


@router.post("/scheduled-scans/{schedule_id}/pause")
async def pause_schedule(request: Request, schedule_id: str):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    try:
        result = await svc.pause(schedule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Schedule not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _redact_response(result)


@router.post("/scheduled-scans/{schedule_id}/resume")
async def resume_schedule(request: Request, schedule_id: str):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    try:
        result = await svc.resume(schedule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Schedule not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _redact_response(result)


@router.post("/scheduled-scans/{schedule_id}/trigger")
async def trigger_schedule(request: Request, schedule_id: str):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    try:
        result = await svc.trigger(schedule_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Schedule not found")
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))
    resp = _redact_response(result)
    if schedule_id in svc.get_running_schedule_ids():
        resp.is_running = True
    return resp


@router.get("/scheduled-scans/{schedule_id}/executions")
async def list_executions(request: Request, schedule_id: str, limit: int = 20):
    _validate_uuid(schedule_id)
    svc = _get_service(request)
    limit = min(max(limit, 1), 100)
    executions = await svc.list_executions(schedule_id, limit=limit)
    return {"executions": [ScheduleExecutionResponse(**e) for e in executions]}
