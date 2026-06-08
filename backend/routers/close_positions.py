"""Close positions router — close-all and conditional rules endpoints."""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.rate_limit import check_rate_limit as _check_rate_limit
from backend.schemas import CreateCloseRuleRequest, UpdateCloseRuleRequest
from backend.services.bybit_client import BybitAPIError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["close-positions"])

_background_tasks: set = set()


def _get_service(request: Request):
    svc = getattr(request.app.state, "close_positions_service", None)
    if svc is None:
        raise HTTPException(503, detail="Close positions feature not available")
    return svc


def _validate_id(value: str, name: str = "ID") -> str:
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail=f"Invalid {name} format") from None
    return value


@router.post("/accounts/{account_id}/positions/close-all")
async def close_all_positions(request: Request, account_id: str):
    _validate_id(account_id, "account ID")
    await _check_rate_limit(account_id)
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


@router.post("/accounts/master-close-all")
async def master_close_all(request: Request):
    """Kill switch: close all positions and delete all rules across ALL accounts (or a subset).
    Returns immediately with a task_id; progress is streamed via WebSocket."""
    svc = _get_service(request)
    accounts_svc = getattr(request.app.state, "accounts_service", None)
    if accounts_svc is None:
        raise HTTPException(503, detail="Accounts service not available")
    ws_mgr = getattr(request.app.state, "account_ws_manager", None)

    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except Exception:
            body = {}
    requested_ids = body.get("account_ids") if isinstance(body, dict) else None

    accounts = await accounts_svc.list_accounts()
    active_accounts = [a for a in accounts if a.get("is_active")]

    if requested_ids:
        requested_set = set(requested_ids)
        active_accounts = [a for a in active_accounts if a["id"] in requested_set]

    if not active_accounts:
        return {"task_id": None, "accounts_total": 0, "message": "No active accounts"}

    task_id = str(_uuid.uuid4())

    async def _run_master_close():
        results = []
        total = len(active_accounts)
        for i, acct in enumerate(active_accounts):
            acct_id = acct["id"]
            acct_name = acct.get("label", "")
            status_entry: dict = {"account_id": acct_id, "name": acct_name}
            try:
                result = await svc.close_all_positions(acct_id)
                status_entry.update({"status": "closed", "closed": result.get("closed", 0), "failed": result.get("failed", 0)})
            except ValueError as e:
                msg = str(e)
                if "in progress" in msg.lower():
                    status_entry.update({"status": "skipped", "reason": msg})
                else:
                    status_entry.update({"status": "error", "reason": msg})
            except BybitAPIError as e:
                status_entry.update({"status": "error", "reason": f"Exchange error ({e.ret_code})"})
            except Exception as e:
                logger.exception("master_close_all failed for %s", acct_id)
                status_entry.update({"status": "error", "reason": str(e)})
            results.append(status_entry)
            if ws_mgr:
                try:
                    await ws_mgr.broadcast_event({
                        "type": "master_close_progress",
                        "task_id": task_id,
                        "current": i + 1,
                        "total": total,
                        "account": status_entry,
                    })
                except Exception:
                    pass

        total_closed = sum(r.get("closed", 0) for r in results)
        total_failed_accounts = sum(1 for r in results if r["status"] == "error")
        if ws_mgr:
            try:
                await ws_mgr.broadcast_event({
                    "type": "master_close_complete",
                    "task_id": task_id,
                    "accounts_processed": len(results),
                    "total_positions_closed": total_closed,
                    "accounts_failed": total_failed_accounts,
                    "results": results,
                })
            except Exception:
                pass

    task = asyncio.create_task(_run_master_close())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"task_id": task_id, "accounts_total": len(active_accounts), "message": "Close operation started"}


@router.post("/accounts/{account_id}/close-rules")
async def create_close_rule(request: Request, account_id: str):
    _validate_id(account_id, "account ID")
    await _check_rate_limit(account_id)
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
