"""Cross-account trade endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid as _uuid
from base64 import b64decode
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.schemas import TradeStatsResponse
from backend.services.trade_repository import SORT_COLUMNS, SYMBOL_PATTERN, VALID_SIDES, VALID_STATUSES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trades"])

_MAX_ACCOUNT_IDS = 50


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


def _get_accounts_service(request: Request):
    svc = getattr(request.app.state, "accounts_service", None)
    if svc is None:
        raise HTTPException(503, detail="Accounts service not available")
    return svc


def _serialize_trade(trade: dict) -> dict:
    out = dict(trade)
    for k, v in out.items():
        if isinstance(v, _uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
    if isinstance(out.get("metadata"), str):
        try:
            out["metadata"] = json.loads(out["metadata"])
        except (json.JSONDecodeError, TypeError):
            out["metadata"] = {}
    return out


def _validate_account_ids(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    if len(ids) > _MAX_ACCOUNT_IDS:
        raise ValueError(f"Maximum {_MAX_ACCOUNT_IDS} account IDs allowed")
    for aid in ids:
        try:
            _uuid.UUID(aid)
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid account ID: {aid}")
    return ids


def _validate_statuses(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    statuses = [s.strip() for s in raw.split(",") if s.strip()]
    for s in statuses:
        if s not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {s}. Allowed: {sorted(VALID_STATUSES)}")
    return statuses


def _validate_date(raw: str | None, name: str) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError(f"Invalid {name}: expected ISO 8601 datetime")


@router.get("/trades")
async def list_trades_cross_account(
    request: Request,
    account_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None, max_length=30),
    side: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
):
    try:
        requested_ids = _validate_account_ids(account_id)
        validated_statuses = _validate_statuses(status)
        validated_from = _validate_date(from_date, "from_date")
        validated_to = _validate_date(to_date, "to_date")

        if symbol and not re.match(SYMBOL_PATTERN, symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        if side:
            normalized_side = side.title()
            if normalized_side not in VALID_SIDES:
                raise ValueError(f"Invalid side: {side}. Allowed: {sorted(VALID_SIDES)}")
        else:
            normalized_side = None
        if sort_by not in SORT_COLUMNS:
            raise ValueError(f"Invalid sort_by: {sort_by}. Allowed: {list(SORT_COLUMNS.keys())}")
        if sort_dir not in ("asc", "desc"):
            raise ValueError(f"Invalid sort_dir: {sort_dir}. Allowed: asc, desc")

        cursor_last_id = None
        cursor_last_sort_value = None
        if cursor:
            try:
                decoded = b64decode(cursor).decode("utf-8")
                parts = decoded.split("|", 1)
                cursor_last_sort_value = parts[0] if parts[0] != "NULL" else None
                cursor_last_id = str(_uuid.UUID(parts[1]))
            except Exception:
                raise ValueError("Invalid cursor format")

    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)

    accounts_svc = _get_accounts_service(request)
    all_accounts = await accounts_svc.list_accounts()
    registered_ids = {a["id"] for a in all_accounts}

    if requested_ids:
        account_ids = [aid for aid in requested_ids if aid in registered_ids]
    else:
        account_ids = list(registered_ids)

    if not account_ids:
        return {"items": [], "cursor": None, "has_more": False}

    repo = _get_trade_repo(request)
    db = _get_db(request)
    async with db.pool.acquire() as conn:
        result = await repo.list_trades_cross_account(
            conn,
            account_ids=account_ids,
            status=validated_statuses,
            symbol=symbol,
            side=normalized_side,
            from_date=validated_from,
            to_date=validated_to,
            sort_by=sort_by,
            sort_dir=sort_dir,
            cursor_last_id=cursor_last_id,
            cursor_last_sort_value=cursor_last_sort_value,
            limit=limit,
        )

    items = result["items"]

    pnl_lookup: dict[tuple[str, str, str, int], float] = {}
    active_statuses = {"open", "partially_filled", "closing", "partially_closed"}
    active_account_ids = {
        str(t["account_id"]) for t in items if t.get("status") in active_statuses
    }
    if active_account_ids:
        accounts_svc = _get_accounts_service(request)
        positions_by_account = await asyncio.gather(
            *(accounts_svc.get_positions(aid) for aid in active_account_ids),
            return_exceptions=True,
        )
        for aid, positions in zip(active_account_ids, positions_by_account):
            if isinstance(positions, Exception):
                continue
            for pos in positions:
                if float(pos.get("size", 0)) == 0:
                    continue
                key = (aid, pos["symbol"], pos["side"], int(pos.get("positionIdx", 0)))
                pnl_lookup[key] = float(pos.get("unrealisedPnl", 0))

    def enrich(trade: dict) -> dict:
        out = _serialize_trade(trade)
        if out.get("status") in active_statuses:
            key = (str(out["account_id"]), out["symbol"], out["side"], out.get("position_idx", 0))
            out["unrealized_pnl"] = pnl_lookup.get(key)
        else:
            out["unrealized_pnl"] = None
        return out

    return {
        "items": [enrich(t) for t in items],
        "cursor": result["cursor"],
        "has_more": result["has_more"],
    }


@router.get("/trades/stats")
async def get_trades_stats_cross_account(
    request: Request,
    account_id: Optional[str] = Query(default=None),
):
    try:
        requested_ids = _validate_account_ids(account_id)
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)

    accounts_svc = _get_accounts_service(request)
    all_accounts = await accounts_svc.list_accounts()
    registered_ids = {a["id"] for a in all_accounts}

    if requested_ids:
        account_ids = [aid for aid in requested_ids if aid in registered_ids]
    else:
        account_ids = list(registered_ids)

    if not account_ids:
        return TradeStatsResponse(
            total_trades=0, open_count=0, win_rate=0, avg_pnl=0, total_pnl=0,
        ).model_dump()

    repo = _get_trade_repo(request)
    db = _get_db(request)
    async with db.pool.acquire() as conn:
        stats = await repo.get_stats_cross_account(conn, account_ids=account_ids)

    return TradeStatsResponse(**stats).model_dump()
