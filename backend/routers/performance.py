"""Performance analytics router — trades-derived KPIs, curve, breakdowns, live."""
from __future__ import annotations

import json
import math
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/performance", tags=["performance"])

_VALID_TIMEFRAMES = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}
_VALID_SORTS = {"net_pnl", "closed_at"}
_VALID_DIRS = {"asc", "desc"}


def _svc(request: Request):
    s = getattr(request.app.state, "performance_service", None)
    if s is None:
        raise HTTPException(503, detail="Performance service not available")
    return s


def _validate_timeframe(tf: str) -> str:
    if tf not in _VALID_TIMEFRAMES:
        raise HTTPException(422, detail=f"timeframe must be one of {sorted(_VALID_TIMEFRAMES)}")
    return tf


def _encode_cursor(cur: tuple | None) -> str | None:
    if cur is None:
        return None
    # allow_nan=False: a non-finite sort value (e.g. inf/nan) would emit invalid JSON the
    # browser's JSON.parse rejects -- fail loudly here instead of shipping a broken cursor.
    return urlsafe_b64encode(json.dumps([cur[0], cur[1]], allow_nan=False).encode()).decode()


def _decode_cursor(raw: str | None, sort: str = "net_pnl") -> tuple | None:
    if not raw:
        return None
    try:
        v, i = json.loads(urlsafe_b64decode(raw.encode()).decode())
    except Exception:  # noqa: BLE001
        raise HTTPException(422, detail="invalid cursor") from None
    # Validate decoded types against the sort mode so a base64/JSON-valid but garbage cursor
    # yields 422 rather than a 500 when the DB layer calls uuid.UUID()/Decimal()/
    # fromisoformat() on it. The id must be a UUID string regardless of sort.
    if not isinstance(i, str):
        raise HTTPException(422, detail="invalid cursor")
    try:
        uuid.UUID(i)  # id is a UUID column; reject a malformed id before it reaches the DB
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(422, detail="invalid cursor") from None
    if v is not None:
        if sort == "net_pnl":
            # numeric required (bool is an int subclass -> excluded); finite
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise HTTPException(422, detail="invalid cursor")
        else:  # closed_at: ISO datetime string
            try:
                datetime.fromisoformat(v)
            except (ValueError, TypeError):
                raise HTTPException(422, detail="invalid cursor") from None
    return (v, i)


@router.get("/overview")
async def get_overview(
    request: Request,
    scope: str = Query("all"),
    timeframe: str = Query("ALL"),
):
    svc = _svc(request)
    _validate_timeframe(timeframe)
    anchor = datetime.now(timezone.utc)
    return await svc.compute_overview(scope=scope, timeframe=timeframe, anchor=anchor)


@router.get("/trades-breakdown")
async def get_trades_breakdown(
    request: Request,
    scope: str = Query("all"),
    timeframe: str = Query("1M"),
):
    svc = _svc(request)
    _validate_timeframe(timeframe)
    anchor = datetime.now(timezone.utc)
    return await svc.compute_breakdowns_for(scope=scope, timeframe=timeframe, anchor=anchor)


@router.get("/trades")
async def get_trades_page(
    request: Request,
    scope: str = Query("all"),
    timeframe: str = Query("ALL"),
    sort: str = Query("net_pnl"),
    dir: str = Query("desc"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    svc = _svc(request)
    _validate_timeframe(timeframe)
    if sort not in _VALID_SORTS:
        raise HTTPException(422, detail=f"sort must be one of {sorted(_VALID_SORTS)}")
    if dir.lower() not in _VALID_DIRS:
        raise HTTPException(422, detail=f"dir must be one of {sorted(_VALID_DIRS)}")
    anchor = datetime.now(timezone.utc)
    result = await svc.compute_trades_page(
        scope=scope, timeframe=timeframe, anchor=anchor,
        sort=sort, direction=dir, cursor=_decode_cursor(cursor, sort), limit=limit,
    )
    # encode the internal (sort_value, id) tuple to an opaque string for the client
    result["cursor"] = _encode_cursor(result.get("cursor"))
    return result


@router.get("/live")
async def get_live(
    request: Request,
    scope: str = Query("all"),
):
    svc = _svc(request)
    return await svc.compute_live(scope=scope)

