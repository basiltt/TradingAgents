"""Trading accounts router — CRUD and portfolio data endpoints."""

from __future__ import annotations

import json
import logging
import time
import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.schemas import (
    CreateAccountRequest,
    PlaceTradeRequest,
    RotateCredentialsRequest,
    TradeCloseRequest,
    TradeDetailResponse,
    TradeListResponse,
    TradeResponse,
    TradeStatsResponse,
    UpdateAccountRequest,
)
from backend.services.bybit_client import BybitAPIError
from backend.services.trade_repository import (
    ConcurrentModification,
    InvalidStatusTransition,
    TradeNotFound,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["accounts"])


class _TokenBucket:
    def __init__(self, rate: float = 10.0, capacity: float = 10.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


_rate_limiters: dict[str, _TokenBucket] = {}
_RATE_LIMITER_MAX_ENTRIES = 1000
_RATE_LIMITER_STALE_SECONDS = 3600


async def _check_rate_limit(account_id: str) -> None:
    now = time.monotonic()
    if len(_rate_limiters) >= _RATE_LIMITER_MAX_ENTRIES:
        stale = [k for k, v in _rate_limiters.items() if now - v.last_refill > _RATE_LIMITER_STALE_SECONDS]
        for k in stale:
            del _rate_limiters[k]
    if account_id not in _rate_limiters:
        if len(_rate_limiters) >= _RATE_LIMITER_MAX_ENTRIES:
            logger.warning("rate_limiter_capacity_exceeded")
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        _rate_limiters[account_id] = _TokenBucket()
    if not _rate_limiters[account_id].consume():
        logger.warning("rate_limit_hit", extra={"account_id": account_id})
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


def _get_service(request: Request):
    svc = request.app.state.accounts_service
    if svc is None:
        raise HTTPException(503, detail="Accounts feature disabled — set ACCOUNTS_ENCRYPTION_KEY")
    return svc


def _validate_account_id(account_id: str) -> str:
    try:
        _uuid.UUID(account_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid account ID format")
    return account_id


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
async def list_accounts(
    request: Request,
    account_type: Optional[str] = Query(None, description="Filter by account type: demo or live"),
):
    svc = _get_service(request)
    accounts = await svc.list_accounts()
    if account_type:
        if account_type not in ("demo", "live"):
            return JSONResponse({"detail": "account_type must be 'demo' or 'live'", "code": "VALIDATION_ERROR"}, 422)
        accounts = [a for a in accounts if a["account_type"] == account_type]
    return accounts


@router.get("/accounts/{account_id}")
async def get_account(request: Request, account_id: str):
    _validate_account_id(account_id)
    svc = _get_service(request)
    account = await svc.get_account(account_id)
    if not account:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return account


@router.patch("/accounts/{account_id}")
async def update_account(request: Request, account_id: str):
    _validate_account_id(account_id)
    body = await request.json()
    try:
        req = UpdateAccountRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    account = await svc.update_account(account_id, label=req.label, is_active=req.is_active)
    if not account:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return account


@router.patch("/accounts/{account_id}/credentials")
async def rotate_credentials(request: Request, account_id: str):
    _validate_account_id(account_id)
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
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        deleted = await svc.delete_account(account_id)
    except Exception as e:
        if "ForeignKeyViolation" in type(e).__name__ or "foreign key" in str(e).lower():
            return JSONResponse(
                {"detail": "Cannot delete account with existing trades", "code": "ACCOUNT_HAS_TRADES"},
                409,
            )
        raise
    if not deleted:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return {"status": "deleted"}


@router.patch("/accounts/{account_id}/analytics-inclusion")
async def toggle_analytics_inclusion(request: Request, account_id: str):
    _validate_account_id(account_id)
    body = await request.json()
    include = body.get("include")
    if not isinstance(include, bool):
        return JSONResponse({"detail": "include must be a boolean", "code": "VALIDATION_ERROR"}, 422)
    svc = _get_service(request)
    result = await svc.set_analytics_inclusion(account_id, include)
    if not result:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return result


@router.post("/accounts/{account_id}/test")
async def test_connection(request: Request, account_id: str):
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        result = await svc.test_connection(account_id)
        return result
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)


@router.post("/accounts/{account_id}/trade")
async def place_trade(request: Request, account_id: str):
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    body = await request.json()
    try:
        req = PlaceTradeRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        result = await svc.place_trade(
            account_id=account_id,
            symbol=req.symbol,
            signal_direction=req.signal_direction,
            trade_direction=req.trade_direction,
            leverage=req.leverage,
            take_profit_pct=req.take_profit_pct,
            stop_loss_pct=req.stop_loss_pct,
            capital_pct=req.capital_pct,
            base_capital=req.base_capital,
        )
        return result
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 400)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/wallet")
async def get_wallet(request: Request, account_id: str):
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        return await svc.get_wallet(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/positions")
async def get_positions(request: Request, account_id: str):
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        return await svc.get_positions(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/orders")
async def get_orders(request: Request, account_id: str):
    _validate_account_id(account_id)
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
    _validate_account_id(account_id)
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
    _validate_account_id(account_id)
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


# --- Trade endpoints ---

def _get_trade_repo(request: Request):
    repo = getattr(request.app.state, "trade_repo", None)
    if repo is None:
        raise HTTPException(503, detail="Trading not configured")
    return repo


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, detail="Database not available")
    return db


def _get_trade_service(request: Request):
    svc = getattr(request.app.state, "trade_service", None)
    return svc


def _serialize_trade(trade: dict) -> dict:
    out = dict(trade)
    for k, v in out.items():
        if isinstance(v, _uuid.UUID):
            out[k] = str(v)
    if isinstance(out.get("metadata"), str):
        try:
            out["metadata"] = json.loads(out["metadata"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("invalid_trade_metadata", extra={"trade_id": out.get("id")})
            out["metadata"] = {}
    return out


@router.get("/accounts/{account_id}/trades")
async def list_trades(
    request: Request,
    account_id: str,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    close_reason: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    sort: str = "created_at",
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = False,
    parent_trade_id: Optional[str] = None,
):
    _validate_account_id(account_id)
    repo = _get_trade_repo(request)
    db = _get_db(request)

    parsed_from = None
    parsed_to = None
    if from_date:
        try:
            parsed_from = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        except ValueError:
            return JSONResponse({"detail": "Invalid from_date format", "code": "VALIDATION_ERROR"}, 400)
    if to_date:
        try:
            parsed_to = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
        except ValueError:
            return JSONResponse({"detail": "Invalid to_date format", "code": "VALIDATION_ERROR"}, 400)

    try:
        async with db.pool.acquire() as conn:
            result = await repo.list_trades(
                conn, account_id=account_id, status=status, symbol=symbol,
                side=side, close_reason=close_reason, from_date=parsed_from,
                to_date=parsed_to, sort=sort, cursor=cursor, limit=limit,
                include_total=include_total, parent_trade_id=parent_trade_id,
            )
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 400)

    return TradeListResponse(
        items=[TradeResponse(**_serialize_trade(t)) for t in result["items"]],
        cursor=result.get("cursor"),
        has_more=result["has_more"],
        total=result.get("total"),
    )


@router.get("/accounts/{account_id}/trades/open")
async def get_open_trades(request: Request, account_id: str):
    _validate_account_id(account_id)
    repo = _get_trade_repo(request)
    db = _get_db(request)
    async with db.pool.acquire() as conn:
        trades = await repo.get_open_trades(conn, account_id=account_id)
    return [TradeResponse(**_serialize_trade(t)) for t in trades]


@router.get("/accounts/{account_id}/trades/stats")
async def get_trade_stats(request: Request, account_id: str):
    _validate_account_id(account_id)
    trade_service = _get_trade_service(request)
    if trade_service is not None:
        stats = await trade_service.get_cached_stats(account_id)
    else:
        repo = _get_trade_repo(request)
        db = _get_db(request)
        async with db.pool.acquire() as conn:
            stats = await repo.get_trade_stats(conn, account_id=account_id)
    return TradeStatsResponse(**stats)


@router.get("/accounts/{account_id}/trades/{trade_id}")
async def get_trade_detail(request: Request, account_id: str, trade_id: str):
    _validate_account_id(account_id)
    try:
        _uuid.UUID(trade_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid trade ID format")

    repo = _get_trade_repo(request)
    db = _get_db(request)
    async with db.pool.acquire() as conn:
        result = await repo.get_trade_with_events(conn, account_id=account_id, trade_id=trade_id)
    if result is None:
        return JSONResponse({"detail": "Trade not found", "code": "TRADE_NOT_FOUND"}, 404)

    trade_data = _serialize_trade(result)
    trade_data["events"] = [
        {**e, "trade_id": str(e["trade_id"])} if "trade_id" in e else e
        for e in trade_data.get("events", [])
    ]
    return TradeDetailResponse(**trade_data)


@router.post("/accounts/{account_id}/trades/{trade_id}/close")
async def close_trade(
    request: Request, account_id: str, trade_id: str,
    body: TradeCloseRequest = TradeCloseRequest(),
):
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    try:
        _uuid.UUID(trade_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid trade ID format")

    trade_service = _get_trade_service(request)
    if trade_service is None:
        return JSONResponse({"detail": "Trading not configured", "code": "SERVICE_UNAVAILABLE"}, 503)

    try:
        result = await trade_service.close_single_trade(
            account_id=account_id, trade_id=trade_id, qty=body.qty,
            close_reason=body.close_reason or "manual_single",
        )
        return TradeResponse(**_serialize_trade(result))
    except TradeNotFound:
        return JSONResponse({"detail": "Trade not found", "code": "TRADE_NOT_FOUND"}, 404)
    except InvalidStatusTransition as e:
        return JSONResponse({"detail": str(e), "code": "INVALID_STATUS_TRANSITION"}, 409)
    except ConcurrentModification as e:
        return JSONResponse({"detail": str(e), "code": "CONCURRENT_MODIFICATION"}, 409)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "EXCHANGE_REJECTION"}, 502)


@router.post("/accounts/{account_id}/trades/{trade_id}/cancel")
async def cancel_trade(request: Request, account_id: str, trade_id: str):
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    try:
        _uuid.UUID(trade_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid trade ID format")

    trade_service = _get_trade_service(request)
    if trade_service is None:
        return JSONResponse({"detail": "Trading not configured", "code": "SERVICE_UNAVAILABLE"}, 503)

    try:
        result = await trade_service.cancel_trade(
            account_id=account_id, trade_id=trade_id,
        )
        return TradeResponse(**_serialize_trade(result))
    except TradeNotFound:
        return JSONResponse({"detail": "Trade not found", "code": "TRADE_NOT_FOUND"}, 404)
    except InvalidStatusTransition as e:
        return JSONResponse({"detail": str(e), "code": "INVALID_STATUS_TRANSITION"}, 409)
    except ConcurrentModification as e:
        return JSONResponse({"detail": str(e), "code": "CONCURRENT_MODIFICATION"}, 409)
    except BybitAPIError as e:
        return JSONResponse({"detail": e.ret_msg, "code": "EXCHANGE_REJECTION"}, 502)
