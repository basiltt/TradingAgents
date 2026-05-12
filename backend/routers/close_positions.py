"""Close positions router — close-all and conditional rules endpoints."""

from __future__ import annotations

import asyncio
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.schemas import CreateCloseRuleRequest, UpdateCloseRuleRequest
from backend.services.bybit_client import BybitAPIError

router = APIRouter(tags=["close-positions"])


def _get_service(request: Request):
    svc = getattr(request.app.state, "close_positions_service", None)
    if svc is None:
        raise HTTPException(503, detail="Close positions feature not available")
    return svc


def _validate_id(value: str, name: str = "ID") -> str:
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail=f"Invalid {name} format")
    return value


@router.post("/accounts/{account_id}/positions/close-all")
async def close_all_positions(request: Request, account_id: str):
    _validate_id(account_id, "account ID")
    svc = _get_service(request)
    try:
        result = await svc.close_all_positions(account_id)
        return result
    except ValueError as e:
        msg = str(e)
        if "in progress" in msg.lower():
            return JSONResponse({"detail": msg, "code": "CLOSE_IN_PROGRESS"}, 409)
        return JSONResponse({"detail": msg, "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        return JSONResponse({"detail": f"Exchange error (code {e.ret_code})", "code": "BYBIT_ERROR"}, 502)


@router.post("/accounts/{account_id}/close-rules")
async def create_close_rule(request: Request, account_id: str):
    _validate_id(account_id, "account ID")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON body", "code": "PARSE_ERROR"}, 400)
    try:
        req = CreateCloseRuleRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        rule = await svc.create_rule(account_id, req.model_dump())
        return JSONResponse(rule, 201)
    except ValueError as e:
        msg = str(e)
        if "maximum" in msg.lower():
            return JSONResponse({"detail": msg, "code": "MAX_RULES_REACHED"}, 409)
        return JSONResponse({"detail": msg, "code": "VALIDATION_ERROR"}, 400)
    except BybitAPIError as e:
        return JSONResponse({"detail": f"Exchange error (code {e.ret_code})", "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/close-rules")
async def list_close_rules(request: Request, account_id: str):
    _validate_id(account_id, "account ID")
    svc = _get_service(request)
    return await svc.list_rules(account_id)


@router.put("/accounts/{account_id}/close-rules/{rule_id}")
async def update_close_rule(request: Request, account_id: str, rule_id: str):
    _validate_id(account_id, "account ID")
    _validate_id(rule_id, "rule ID")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON body", "code": "PARSE_ERROR"}, 400)
    try:
        req = UpdateCloseRuleRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        result = await svc.update_rule(account_id, rule_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 400)
    if not result:
        return JSONResponse({"detail": "Rule not found", "code": "NOT_FOUND"}, 404)
    return result


@router.delete("/accounts/{account_id}/close-rules/{rule_id}")
async def delete_close_rule(request: Request, account_id: str, rule_id: str):
    _validate_id(account_id, "account ID")
    _validate_id(rule_id, "rule ID")
    svc = _get_service(request)
    deleted = await svc.delete_rule(account_id, rule_id)
    if not deleted:
        return JSONResponse({"detail": "Rule not found", "code": "NOT_FOUND"}, 404)
    return {"status": "deleted"}


@router.get("/accounts/{account_id}/close-executions")
async def list_close_executions(
    request: Request,
    account_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    _validate_id(account_id, "account ID")
    svc = _get_service(request)
    return await svc.list_executions(account_id, page, limit)
