"""Trading accounts router — CRUD and portfolio data endpoints."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.schemas import CreateAccountRequest, UpdateAccountRequest, RotateCredentialsRequest
from backend.services.bybit_client import BybitAPIError

router = APIRouter(tags=["accounts"])


def _get_service(request: Request):
    svc = request.app.state.accounts_service
    if svc is None:
        raise HTTPException(503, detail="Accounts feature disabled — set ACCOUNTS_ENCRYPTION_KEY")
    return svc


@router.post("/accounts")
async def create_account(request: Request):
    body = await request.json()
    try:
        req = CreateAccountRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        account = await svc.create_account(req.label, req.account_type, req.api_key, req.api_secret)
        return account
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "CREDENTIAL_VALIDATION_FAILED"}, 400)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts")
async def list_accounts(request: Request):
    svc = _get_service(request)
    return svc.list_accounts()


@router.get("/accounts/{account_id}")
async def get_account(request: Request, account_id: str):
    svc = _get_service(request)
    account = svc.get_account(account_id)
    if not account:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return account


@router.patch("/accounts/{account_id}")
async def update_account(request: Request, account_id: str):
    body = await request.json()
    try:
        req = UpdateAccountRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    account = svc.update_account(account_id, label=req.label, is_active=req.is_active)
    if not account:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return account


@router.patch("/accounts/{account_id}/credentials")
async def rotate_credentials(request: Request, account_id: str):
    body = await request.json()
    try:
        req = RotateCredentialsRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        account = await svc.rotate_credentials(account_id, req.api_key, req.api_secret)
        if not account:
            return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
        return account
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "CREDENTIAL_VALIDATION_FAILED"}, 400)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.delete("/accounts/{account_id}")
async def delete_account(request: Request, account_id: str):
    svc = _get_service(request)
    deleted = svc.delete_account(account_id)
    if not deleted:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return {"status": "deleted"}


@router.post("/accounts/{account_id}/test")
async def test_connection(request: Request, account_id: str):
    svc = _get_service(request)
    try:
        result = await svc.test_connection(account_id)
        return result
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)


@router.get("/accounts/{account_id}/wallet")
async def get_wallet(request: Request, account_id: str):
    svc = _get_service(request)
    try:
        return await svc.get_wallet(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/positions")
async def get_positions(request: Request, account_id: str):
    svc = _get_service(request)
    try:
        return await svc.get_positions(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/orders")
async def get_orders(request: Request, account_id: str):
    svc = _get_service(request)
    try:
        return await svc.get_orders(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/closed-pnl")
async def get_closed_pnl(
    request: Request,
    account_id: str,
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=1000),
):
    try:
        date.fromisoformat(start_date)
        date.fromisoformat(end_date)
    except ValueError:
        return JSONResponse({"detail": "Invalid date format, expected YYYY-MM-DD", "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        return await svc.get_closed_pnl(account_id, start_date, end_date, page, limit)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/closed-pnl/summary")
async def get_pnl_summary(
    request: Request,
    account_id: str,
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
):
    try:
        date.fromisoformat(start_date)
        date.fromisoformat(end_date)
    except ValueError:
        return JSONResponse({"detail": "Invalid date format, expected YYYY-MM-DD", "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        return await svc.get_pnl_summary(account_id, start_date, end_date)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)
