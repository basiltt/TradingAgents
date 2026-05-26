"""AI Manager REST API Router — Phase 4 Task 4.1."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.ai_manager_schemas import AIManagerConfigPatch
from backend.rate_limit import check_rate_limit as _check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai-manager"])


def _get_service(request: Request):
    svc = getattr(request.app.state, "ai_manager_service", None)
    if svc is None:
        raise HTTPException(503, detail="AI Manager feature not available")
    return svc


# --- Enable / Disable ---


@router.post("/accounts/{account_id}/ai-manager/enable")
async def enable_ai_manager(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    from backend.ai_manager_schemas import AIManagerConfig
    config = AIManagerConfig()
    existing_state = await svc.get_status(account_id)
    if existing_state and existing_state.enabled:
        return {"status": "enabled", "account_id": account_id}
    await svc.enable(account_id, config)
    return {"status": "enabled", "account_id": account_id}


@router.post("/accounts/{account_id}/ai-manager/disable")
async def disable_ai_manager(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.disable(account_id)
    return {"status": "disabled", "account_id": account_id}


# --- Status ---


@router.get("/accounts/{account_id}/ai-manager/status")
async def get_ai_manager_status(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    status = await svc.get_status(account_id)
    if status is None:
        raise HTTPException(404, detail="AI Manager not configured for this account")
    return status


# --- Config ---


@router.get("/accounts/{account_id}/ai-manager/config")
async def get_config(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    try:
        config = await svc.get_config(account_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return config


@router.patch("/accounts/{account_id}/ai-manager/config")
async def patch_config(request: Request, account_id: str, body: AIManagerConfigPatch):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, detail="No fields provided")
    try:
        await svc.patch_config(account_id, updates)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return {"status": "updated", "account_id": account_id}


# --- Pause / Resume ---


@router.post("/accounts/{account_id}/ai-manager/pause")
async def pause_ai_manager(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.pause(account_id)
    return {"status": "paused", "account_id": account_id}


@router.post("/accounts/{account_id}/ai-manager/resume")
async def resume_ai_manager(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.resume(account_id)
    return {"status": "resumed", "account_id": account_id}


# --- Kill / Kill Reset ---


@router.post("/accounts/{account_id}/ai-manager/kill")
async def kill_ai_manager(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.kill(account_id)
    return {"status": "killed", "account_id": account_id}


@router.post("/accounts/{account_id}/ai-manager/kill/reset")
async def reset_kill_switch(request: Request, account_id: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.reset_kill_switch(account_id)
    return {"status": "kill_switch_reset", "account_id": account_id}


# --- Position Locking ---


@router.post("/accounts/{account_id}/ai-manager/positions/{symbol}/lock")
async def lock_position(request: Request, account_id: str, symbol: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    try:
        await svc.lock_position(account_id, symbol)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return {"status": "locked", "account_id": account_id, "symbol": symbol}


@router.delete("/accounts/{account_id}/ai-manager/positions/{symbol}/lock")
async def unlock_position(request: Request, account_id: str, symbol: str):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    try:
        await svc.unlock_position(account_id, symbol)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return {"status": "unlocked", "account_id": account_id, "symbol": symbol}


# --- Decisions ---


@router.get("/accounts/{account_id}/ai-manager/decisions")
async def get_decisions(
    request: Request,
    account_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    result = await svc.get_decisions(account_id, limit=limit, cursor=cursor, outcome_filter=outcome)
    return result


# --- Performance ---


@router.get("/accounts/{account_id}/ai-manager/performance")
async def get_performance(
    request: Request,
    account_id: str,
    period: str = Query(default="7d", pattern="^(1d|7d|30d)$"),
):
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    result = await svc.get_performance(account_id, period=period)
    return result


# --- Global Kill ---


@router.post("/ai-manager/global-kill")
async def global_kill(request: Request):
    svc = _get_service(request)
    await svc.global_kill()
    return {"status": "global_kill_activated"}
