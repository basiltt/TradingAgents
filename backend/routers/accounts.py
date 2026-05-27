"""Trading accounts router — CRUD and portfolio data endpoints."""

from __future__ import annotations

import asyncio
import logging
import math
import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.rate_limit import check_rate_limit as _check_rate_limit
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
from backend.utils import serialize_trade as _serialize_trade, validate_trade_id as _validate_trade_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["accounts"])

_background_tasks: set = set()


def _validate_id(value: str, name: str = "ID") -> str:
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail=f"Invalid {name} format")
    return value


def _get_service(request: Request):
    """Retrieve AccountsService from app state or raise 503."""
    svc = getattr(request.app.state, "accounts_service", None)
    if svc is None:
        raise HTTPException(503, detail="Accounts feature disabled — set ACCOUNTS_ENCRYPTION_KEY")
    return svc


def _validate_account_id(account_id: str) -> str:
    """Validate UUID format and return the ID, or raise HTTPException(400)."""
    try:
        _uuid.UUID(account_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid account ID format")
    return account_id


@router.post("/accounts")
async def create_account(request: Request):
    """Create a new trading account with encrypted API credentials."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON body", "code": "PARSE_ERROR"}, 400)
    try:
        req = CreateAccountRequest(**body)
    except ValidationError as e:
        return JSONResponse({"detail": e.errors()[0]["msg"], "code": "VALIDATION_ERROR"}, 422)

    svc = _get_service(request)
    try:
        account = await svc.create_account(req.label, req.account_type, req.api_key, req.api_secret)
        logger.info("create_account_ok", extra={"account_id": account.get("id")})
        return account
    except ValueError as e:
        logger.warning("create_account_credential_failed", extra={"error": str(e)[:200]})
        return JSONResponse({"detail": str(e), "code": "CREDENTIAL_VALIDATION_FAILED"}, 400)
    except BybitAPIError as e:
        logger.error("create_account_bybit_error", extra={"ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts")
async def list_accounts(
    request: Request,
    account_type: Optional[str] = Query(None, description="Filter by account type: demo or live"),
):
    """List all trading accounts, optionally filtered by type."""
    svc = _get_service(request)
    accounts = await svc.list_accounts()
    if account_type:
        if account_type not in ("demo", "live"):
            return JSONResponse({"detail": "account_type must be 'demo' or 'live'", "code": "VALIDATION_ERROR"}, 422)
        accounts = [a for a in accounts if a["account_type"] == account_type]
    return accounts


@router.get("/accounts/{account_id}")
async def get_account(request: Request, account_id: str):
    """Fetch a single account by ID."""
    _validate_account_id(account_id)
    svc = _get_service(request)
    account = await svc.get_account(account_id)
    if not account:
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    return account


@router.patch("/accounts/{account_id}")
async def update_account(request: Request, account_id: str):
    """Update account label or active status."""
    _validate_account_id(account_id)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON body", "code": "PARSE_ERROR"}, 400)
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
    """Replace API credentials and verify connectivity."""
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
        logger.info("rotate_credentials_ok", extra={"account_id": account_id})
        return account
    except ValueError as e:
        logger.warning("rotate_credentials_failed", extra={"account_id": account_id, "error": str(e)[:200]})
        return JSONResponse({"detail": str(e), "code": "CREDENTIAL_VALIDATION_FAILED"}, 400)
    except BybitAPIError as e:
        logger.error("rotate_credentials_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.delete("/accounts/{account_id}")
async def delete_account(request: Request, account_id: str):
    """Soft-delete an account and invalidate cached data."""
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        deleted = await svc.delete_account(account_id)
    except Exception as e:
        logger.error("delete_account_failed", extra={"account_id": account_id, "error": str(e)[:200]})
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
    """Toggle whether this account is included in portfolio analytics."""
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
    """Test exchange API connectivity for an account."""
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        result = await svc.test_connection(account_id)
        return result
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)


@router.post("/accounts/{account_id}/trade")
async def place_trade(request: Request, account_id: str):
    """Place a market trade with leverage, TP, and SL on the exchange."""
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
        logger.error("place_trade_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/wallet")
async def get_wallet(request: Request, account_id: str):
    """Fetch wallet balances for an account."""
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        return await svc.get_wallet(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        logger.error("get_wallet_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/positions")
async def get_positions(request: Request, account_id: str):
    """Fetch open perpetual positions for an account."""
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        return await svc.get_positions(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        logger.error("get_positions_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/orders")
async def get_orders(request: Request, account_id: str):
    """Fetch active orders for an account."""
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        return await svc.get_orders(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "NOT_FOUND"}, 404)
    except BybitAPIError as e:
        logger.error("get_orders_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
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
    """Fetch closed PnL records for an account within a date range."""
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
        logger.error("get_closed_pnl_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


@router.get("/accounts/{account_id}/closed-pnl/summary")
async def get_pnl_summary(
    request: Request,
    account_id: str,
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
):
    """Compute aggregated PnL summary (total, win rate, avg) for a date range."""
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
        logger.error("get_pnl_summary_bybit_error", extra={"account_id": account_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "BYBIT_ERROR"}, 502)


# --- Trade endpoints ---

def _get_trade_repo(request: Request):
    """Retrieve TradeRepository from app state or raise 503."""
    repo = getattr(request.app.state, "trade_repo", None)
    if repo is None:
        raise HTTPException(503, detail="Trading not configured")
    return repo


def _get_db(request: Request):
    """Retrieve AsyncAnalysisDB from app state or raise 503."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, detail="Database not available")
    return db


def _get_trade_service(request: Request):
    """Retrieve TradeService from app state, or None if not configured."""
    svc = getattr(request.app.state, "trade_service", None)
    return svc




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
    """List trades for an account with filtering, sorting, and cursor pagination."""
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
    """Fetch all currently open trades for an account."""
    _validate_account_id(account_id)
    repo = _get_trade_repo(request)
    db = _get_db(request)
    async with db.pool.acquire() as conn:
        trades = await repo.get_open_trades(conn, account_id=account_id)
    return [TradeResponse(**_serialize_trade(t)) for t in trades]


@router.get("/accounts/{account_id}/trades/stats")
async def get_trade_stats(request: Request, account_id: str):
    """Fetch aggregated trade statistics for an account."""
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
    """Fetch a single trade with its event history."""
    _validate_account_id(account_id)
    _validate_trade_id(trade_id)

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


def _serialize_trade_event(event: dict) -> dict:
    """Serialize a trade event dict, converting UUIDs and datetimes to strings."""
    out = dict(event)
    for k, v in out.items():
        if isinstance(v, _uuid.UUID):
            out[k] = str(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out


@router.get("/accounts/{account_id}/trades/{trade_id}/events")
async def get_trade_events(request: Request, account_id: str, trade_id: str):
    """Fetch audit trail events for a specific trade."""
    _validate_account_id(account_id)
    try:
        _uuid.UUID(trade_id)
    except (ValueError, AttributeError):
        return JSONResponse({"detail": "Invalid trade_id", "code": "VALIDATION_ERROR"}, 422)

    repo = _get_trade_repo(request)
    db = _get_db(request)
    async with db.pool.acquire() as conn:
        trade = await repo.get_trade(conn, account_id=account_id, trade_id=trade_id)
        if not trade:
            return JSONResponse({"detail": "Trade not found", "code": "TRADE_NOT_FOUND"}, 404)
        events = await conn.fetch(
            "SELECT * FROM trade_events WHERE trade_id = $1 ORDER BY created_at ASC LIMIT 1000",
            _uuid.UUID(trade_id),
        )
    items = [_serialize_trade_event(dict(e)) for e in events]
    return {"items": items, "truncated": len(events) >= 1000}


@router.post("/accounts/{account_id}/trades/{trade_id}/close")
async def close_trade(
    request: Request, account_id: str, trade_id: str,
    body: TradeCloseRequest = TradeCloseRequest(),
):
    """Close a trade (full or partial) via the exchange."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    _validate_trade_id(trade_id)

    trade_service = _get_trade_service(request)
    if trade_service is None:
        return JSONResponse({"detail": "Trading not configured", "code": "SERVICE_UNAVAILABLE"}, 503)

    try:
        result = await trade_service.close_single_trade(
            account_id=account_id, trade_id=trade_id, qty=body.qty,
            close_reason=body.close_reason or "manual_single",
        )
        logger.info("close_trade_ok", extra={"account_id": account_id, "trade_id": trade_id})
        return TradeResponse(**_serialize_trade(result))
    except TradeNotFound:
        return JSONResponse({"detail": "Trade not found", "code": "TRADE_NOT_FOUND"}, 404)
    except InvalidStatusTransition as e:
        return JSONResponse({"detail": str(e), "code": "INVALID_STATUS_TRANSITION"}, 409)
    except ConcurrentModification as e:
        return JSONResponse({"detail": str(e), "code": "CONCURRENT_MODIFICATION"}, 409)
    except BybitAPIError as e:
        logger.error("close_trade_bybit_error", extra={"account_id": account_id, "trade_id": trade_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "EXCHANGE_REJECTION"}, 502)


@router.post("/accounts/{account_id}/trades/{trade_id}/cancel")
async def cancel_trade(request: Request, account_id: str, trade_id: str):
    """Cancel a pending or open trade."""
    _validate_account_id(account_id)
    await _check_rate_limit(account_id)
    _validate_trade_id(trade_id)

    trade_service = _get_trade_service(request)
    if trade_service is None:
        return JSONResponse({"detail": "Trading not configured", "code": "SERVICE_UNAVAILABLE"}, 503)

    try:
        result = await trade_service.cancel_trade(
            account_id=account_id, trade_id=trade_id,
        )
        logger.info("cancel_trade_ok", extra={"account_id": account_id, "trade_id": trade_id})
        return TradeResponse(**_serialize_trade(result))
    except TradeNotFound:
        return JSONResponse({"detail": "Trade not found", "code": "TRADE_NOT_FOUND"}, 404)
    except InvalidStatusTransition as e:
        return JSONResponse({"detail": str(e), "code": "INVALID_STATUS_TRANSITION"}, 409)
    except ConcurrentModification as e:
        return JSONResponse({"detail": str(e), "code": "CONCURRENT_MODIFICATION"}, 409)
    except BybitAPIError as e:
        logger.error("cancel_trade_bybit_error", extra={"account_id": account_id, "trade_id": trade_id, "ret_msg": e.ret_msg[:200]})
        return JSONResponse({"detail": e.ret_msg, "code": "EXCHANGE_REJECTION"}, 502)


@router.post("/accounts/demo-reset-balance")
async def demo_reset_balance(request: Request):
    """Set USDT balance for selected demo accounts to a target amount.
    Accepts optional account_ids list; defaults to all active demo accounts.
    Returns immediately with a task_id; progress is streamed via WebSocket."""
    svc = _get_service(request)
    ws_mgr = getattr(request.app.state, "account_ws_manager", None)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON body"}, 400)

    try:
        target = float(body.get("target_balance", 0))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "target_balance must be a number"}, 400)
    if target <= 0 or target > 100000:
        return JSONResponse({"detail": "target_balance must be between 0.01 and 100000"}, 400)

    account_ids = body.get("account_ids")  # optional list of specific account IDs
    if account_ids is not None:
        if not isinstance(account_ids, list) or not all(isinstance(x, str) for x in account_ids):
            return JSONResponse({"detail": "account_ids must be a list of strings"}, 400)
        for aid in account_ids:
            _validate_id(aid, "account ID")

    accounts = await svc.list_accounts()
    demo_accounts = [a for a in accounts if a.get("account_type") == "demo" and a.get("is_active")]

    if account_ids:
        id_set = set(account_ids)
        demo_accounts = [a for a in demo_accounts if a["id"] in id_set]

    if not demo_accounts:
        return JSONResponse({"detail": "No active demo accounts found"}, 404)

    task_id = str(_uuid.uuid4())

    async def _run_reset():
        results = []
        total = len(demo_accounts)
        for i, acct in enumerate(demo_accounts):
            acct_id = acct["id"]
            acct_name = acct.get("label", "")
            entry: dict = {"account_id": acct_id, "name": acct_name}
            try:
                client = await svc.get_client(acct_id)
                wallet = await client.get_wallet_balance()
                current_balance = float(wallet.get("totalWalletBalance") or "0")
                diff = target - current_balance
                # Bybit demo-apply-money only accepts integer amounts; ceil to ensure we reach target
                abs_amount = math.ceil(abs(diff))
                if abs_amount < 1:
                    entry.update({"status": "unchanged", "balance": current_balance})
                elif diff > 0:
                    remaining = abs_amount
                    while remaining > 0:
                        chunk = min(remaining, 100000)
                        await client.demo_apply_money("USDT", str(chunk))
                        remaining -= chunk
                        if remaining > 0:
                            await asyncio.sleep(0.3)
                    entry.update({"status": "added", "amount": abs_amount, "new_balance": round(current_balance + abs_amount, 2)})
                else:
                    remaining = abs_amount
                    while remaining > 0:
                        chunk = min(remaining, 100000)
                        await client.demo_apply_money("USDT", str(chunk), reduce=True)
                        remaining -= chunk
                        if remaining > 0:
                            await asyncio.sleep(0.3)
                    entry.update({"status": "reduced", "amount": abs_amount, "new_balance": round(current_balance - abs_amount, 2)})
                if i < total - 1:
                    await asyncio.sleep(0.5)
            except BybitAPIError as e:
                entry.update({"status": "error", "reason": e.ret_msg})
            except Exception as e:
                logger.exception("demo_reset_balance failed for %s", acct_id)
                entry.update({"status": "error", "reason": str(e)})
            results.append(entry)
            if ws_mgr:
                try:
                    await ws_mgr.broadcast_event({
                        "type": "demo_reset_progress",
                        "task_id": task_id,
                        "current": i + 1,
                        "total": total,
                        "account": entry,
                    })
                except Exception:
                    pass

        svc.invalidate_all_caches()
        success_count = sum(1 for r in results if r["status"] in ("added", "reduced", "unchanged"))
        if ws_mgr:
            try:
                await ws_mgr.broadcast_event({
                    "type": "demo_reset_complete",
                    "task_id": task_id,
                    "target_balance": target,
                    "accounts_processed": len(results),
                    "success": success_count,
                    "results": results,
                })
            except Exception:
                pass

    task = asyncio.create_task(_run_reset())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"task_id": task_id, "accounts_total": len(demo_accounts), "message": "Balance reset started"}
