"""AI Manager REST API Router — Phase 4 Task 4.1."""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.ai_manager_schemas import AIManagerConfigPatch
from backend.rate_limit import check_rate_limit as _check_rate_limit
from backend.routers._validators import validate_account_id as _validate_account_id
from backend.schemas.ai_manager_dashboard import (
    LLMCallEntry, LLMCallListResponse, CapabilitiesResponse,
    MarketInsightResponse, AnalysisContextResponse, ErrorResponse,
)
from backend.services.ai_manager_capabilities_status import CapabilitiesStatusAggregator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai-manager"])

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,20}$")



def _validate_symbol(symbol: str) -> str:
    """Validate symbol format (uppercase alphanumeric, max 20 chars)."""
    if not _SYMBOL_PATTERN.match(symbol):
        raise HTTPException(400, detail="Invalid symbol format")
    return symbol


def _get_service(request: Request):
    svc = getattr(request.app.state, "ai_manager_service", None)
    if svc is None:
        raise HTTPException(503, detail="AI Manager feature not available")
    return svc


# --- Enable / Disable ---


@router.post("/accounts/{account_id}/ai-manager/enable")
async def enable_ai_manager(request: Request, account_id: str):
    """Enable AI Manager for the specified account."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    from backend.ai_manager_schemas import AIManagerConfig
    
    existing_config = None
    try:
        existing_config = await svc.get_config(account_id)
    except Exception:
        pass

    if existing_config:
        config = AIManagerConfig(**existing_config)
    else:
        config = AIManagerConfig()
    
    config.auto_enabled = False
    await svc.enable(account_id, config)
    return {"status": "enabled", "account_id": account_id}


@router.post("/accounts/{account_id}/ai-manager/disable")
async def disable_ai_manager(request: Request, account_id: str):
    """Disable AI Manager and stop the decision loop for this account."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.disable(account_id)
    return {"status": "disabled", "account_id": account_id}


# --- Status ---


@router.get("/accounts/{account_id}/ai-manager/status")
async def get_ai_manager_status(request: Request, account_id: str):
    """Return current AI Manager status including FSM state and telemetry."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    status = await svc.get_status(account_id)
    if status is None:
        raise HTTPException(404, detail="AI Manager not configured for this account")
    return status


# --- Config ---


@router.get("/accounts/{account_id}/ai-manager/config")
async def get_config(request: Request, account_id: str):
    """Retrieve the current AI Manager configuration for this account."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    try:
        config = await svc.get_config(account_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return config


@router.patch("/accounts/{account_id}/ai-manager/config")
async def patch_config(request: Request, account_id: str, body: AIManagerConfigPatch):
    """Partially update AI Manager configuration fields."""
    _validate_account_id(account_id)
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
    """Pause the AI decision loop; positions remain open but unmanaged."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.pause(account_id)
    return {"status": "paused", "account_id": account_id}


@router.post("/accounts/{account_id}/ai-manager/resume")
async def resume_ai_manager(request: Request, account_id: str):
    """Resume a paused AI Manager decision loop."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.resume(account_id)
    return {"status": "resumed", "account_id": account_id}


# --- Kill / Kill Reset ---


@router.post("/accounts/{account_id}/ai-manager/kill")
async def kill_ai_manager(request: Request, account_id: str):
    """Activate kill switch — halts all AI decisions until manually reset."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.kill(account_id)
    return {"status": "killed", "account_id": account_id}


@router.post("/accounts/{account_id}/ai-manager/kill/reset")
async def reset_kill_switch(request: Request, account_id: str):
    """Reset a previously activated kill switch, allowing AI decisions to resume."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    await svc.reset_kill_switch(account_id)
    return {"status": "kill_switch_reset", "account_id": account_id}


# --- Position Locking ---


@router.post("/accounts/{account_id}/ai-manager/positions/{symbol}/lock")
async def lock_position(request: Request, account_id: str, symbol: str):
    """Lock a position to prevent AI from closing it."""
    _validate_account_id(account_id)
    _validate_symbol(symbol)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    try:
        await svc.lock_position(account_id, symbol)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return {"status": "locked", "account_id": account_id, "symbol": symbol}


@router.delete("/accounts/{account_id}/ai-manager/positions/{symbol}/lock")
async def unlock_position(request: Request, account_id: str, symbol: str):
    """Remove position lock, allowing AI to manage it again."""
    _validate_account_id(account_id)
    _validate_symbol(symbol)
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
    """List AI Manager decisions with cursor-based pagination."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    result = await svc.get_decisions(account_id, limit=limit, cursor=cursor, outcome_filter=outcome)
    return result


# --- Logs ---


@router.get("/accounts/{account_id}/ai-manager/logs")
async def get_logs(
    request: Request,
    account_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    level: Optional[str] = Query(default=None, pattern="^(debug|info|warning|error|critical)$"),
    category: Optional[str] = Query(default=None),
    cursor: Optional[int] = Query(default=None),
):
    """Retrieve AI Manager operational logs with optional level/category filtering."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    result = await svc.get_logs(
        account_id, limit=limit, level=level, category=category, cursor_id=cursor,
    )
    return result


# --- Performance ---


@router.get("/accounts/{account_id}/ai-manager/performance")
async def get_performance(
    request: Request,
    account_id: str,
    period: str = Query(default="7d", pattern="^(1d|7d|30d)$"),
):
    """Return AI Manager performance metrics for the given time period."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    result = await svc.get_performance(account_id, period=period)
    return result


# --- Global Kill ---


@router.post("/ai-manager/global-kill")
async def global_kill(request: Request):
    """Activate global kill switch — halts ALL AI Manager instances across all accounts."""
    await _check_rate_limit("global-kill")
    svc = _get_service(request)
    await svc.global_kill()
    return {"status": "global_kill_activated"}


# --- Dashboard Enhancement Endpoints ---


@router.get(
    "/accounts/{account_id}/ai-manager/llm-calls",
    response_model=LLMCallListResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_llm_calls(
    request: Request,
    account_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
):
    """Get paginated LLM call history for account."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    task = svc.get_task(account_id)
    if task is None:
        raise HTTPException(404, detail="Account not found or AI Manager not active")

    cursor_ts, cursor_id = None, None
    if cursor:
        try:
            parts = cursor.split("|")
            cursor_ts, cursor_id = parts[0], int(parts[1])
        except (ValueError, IndexError):
            raise HTTPException(400, detail="Invalid cursor format")

    calls, next_cursor = await svc._repo.get_llm_calls(
        account_id, limit=limit, cursor_timestamp=cursor_ts, cursor_id=cursor_id
    )
    return LLMCallListResponse(
        calls=[LLMCallEntry(**{k: v for k, v in c.items() if k != "account_id"}) for c in calls],
        next_cursor=next_cursor,
    )


@router.get(
    "/accounts/{account_id}/ai-manager/capabilities-status",
    response_model=CapabilitiesResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_capabilities_status(request: Request, account_id: str):
    """Get current status of all AI Manager capabilities."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    task = svc.get_task(account_id)
    if task is None:
        raise HTTPException(404, detail="Account not found or AI Manager not active")

    aggregator = CapabilitiesStatusAggregator(
        config=task._config.model_dump(),
        degradation_tier=task._degradation_tier,
        task_state=task._get_dashboard_state(),
        evaluation_interval_s=getattr(task._config, "evaluation_interval_s", 60),
        next_eval_at=task._next_eval_at,
    )
    return CapabilitiesResponse(**aggregator.get_response())


@router.get(
    "/accounts/{account_id}/ai-manager/market-insights",
    response_model=MarketInsightResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_market_insights(request: Request, account_id: str):
    """Get market insights including day score and latest commentary."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    task = svc.get_task(account_id)
    if task is None:
        raise HTTPException(404, detail="Account not found or AI Manager not active")

    commentary = await svc._repo.get_latest_commentary(account_id)
    context = task._get_analysis_context()

    return MarketInsightResponse(
        day_score=commentary.get("day_score") if commentary else None,
        day_score_label=commentary.get("day_score_label") if commentary else None,
        day_score_justification=context.get("day_score_justification"),
        latest_commentary=commentary,
        regime=context.get("regime"),
        session=context.get("session"),
        correlation_heat=context.get("correlation_heat"),
        active_sweeps=context.get("active_sweeps", []),
        positions_health=context.get("positions_health", []),
    )


@router.get(
    "/accounts/{account_id}/ai-manager/analysis-context",
    response_model=AnalysisContextResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_analysis_context(request: Request, account_id: str):
    """Get current analysis enrichment context without triggering new analysis."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    svc = _get_service(request)
    task = svc.get_task(account_id)
    if task is None:
        raise HTTPException(404, detail="Account not found or AI Manager not active")

    context = task._get_analysis_context()
    return AnalysisContextResponse(**context)
