"""Strategies router — CRUD and import/export endpoints."""

from __future__ import annotations

import json
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.schemas import (
    VALID_STRATEGY_CATEGORIES,
    VALID_STRATEGY_STATUSES,
    CreateStrategyRequest,
    UpdateStrategyRequest,
)

router = APIRouter(tags=["strategies"])

MAX_IMPORT_BATCH = 100


def _get_service(request: Request):
    svc = request.app.state.strategy_service
    if svc is None:
        raise HTTPException(503, detail="Strategies feature not available")
    return svc


def _validate_id(strategy_id: str) -> str:
    try:
        _uuid.UUID(strategy_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid strategy ID format") from None
    return strategy_id


@router.get("/strategies")
async def list_strategies(
    request: Request,
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    if status and status not in VALID_STRATEGY_STATUSES:
        return JSONResponse({"detail": f"Invalid status filter: {status}", "code": "VALIDATION_ERROR"}, 422)
    if category and category not in VALID_STRATEGY_CATEGORIES:
        return JSONResponse({"detail": f"Invalid category filter: {category}", "code": "VALIDATION_ERROR"}, 422)
    svc = _get_service(request)
    items = await svc.list_strategies(status=status, category=category)
    return items


@router.post("/strategies")
async def create_strategy(request: Request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"detail": "Invalid JSON body", "code": "INVALID_JSON"}, 400)
    try:
        req = CreateStrategyRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)
    svc = _get_service(request)
    strategy = await svc.create_strategy(req.model_dump())
    return strategy


@router.get("/strategies/export")
async def export_strategies(request: Request):
    svc = _get_service(request)
    items = await svc.list_strategies()
    return {"strategies": items}


@router.post("/strategies/import")
async def import_strategies(request: Request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"detail": "Invalid JSON body", "code": "INVALID_JSON"}, 400)
    strategies = body if isinstance(body, list) else body.get("strategies", [])
    if not strategies:
        return JSONResponse({"detail": "No strategies provided", "code": "VALIDATION_ERROR"}, 422)
    if len(strategies) > MAX_IMPORT_BATCH:
        return JSONResponse({"detail": f"Too many strategies (max {MAX_IMPORT_BATCH})", "code": "VALIDATION_ERROR"}, 422)
    validated = []
    errors = []
    for i, s in enumerate(strategies):
        if not isinstance(s, dict):
            errors.append(f"Item {i}: not an object")
            continue
        try:
            validated.append(CreateStrategyRequest(**s).model_dump())
        except ValidationError as e:
            errors.append(f"Item {i}: {e.errors()[0]['msg']}")
    if errors:
        return JSONResponse({"detail": f"Validation errors: {'; '.join(errors)}", "code": "VALIDATION_ERROR"}, 422)
    svc = _get_service(request)
    imported = await svc.import_strategies(validated)
    return {"imported": len(imported), "strategies": imported}


@router.get("/strategies/{strategy_id}")
async def get_strategy(request: Request, strategy_id: str):
    _validate_id(strategy_id)
    svc = _get_service(request)
    strategy = await svc.get_strategy(strategy_id)
    if not strategy:
        return JSONResponse({"detail": "Strategy not found", "code": "NOT_FOUND"}, 404)
    return strategy


@router.patch("/strategies/{strategy_id}")
async def update_strategy(request: Request, strategy_id: str):
    _validate_id(strategy_id)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"detail": "Invalid JSON body", "code": "INVALID_JSON"}, 400)
    try:
        req = UpdateStrategyRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)
    svc = _get_service(request)
    updates = req.model_dump(exclude_unset=True)
    result = await svc.update_strategy(strategy_id, updates)
    if result is None:
        return JSONResponse({"detail": "Strategy not found", "code": "NOT_FOUND"}, 404)
    return result


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(request: Request, strategy_id: str):
    _validate_id(strategy_id)
    svc = _get_service(request)
    ok = await svc.delete_strategy(strategy_id)
    if not ok:
        return JSONResponse({"detail": "Strategy not found", "code": "NOT_FOUND"}, 404)
    return {"deleted": True}
