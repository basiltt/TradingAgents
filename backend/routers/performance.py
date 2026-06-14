"""Performance analytics router — trades-derived KPIs, curve, breakdowns, live."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/performance", tags=["performance"])

_VALID_TIMEFRAMES = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}


def _svc(request: Request):
    s = getattr(request.app.state, "performance_service", None)
    if s is None:
        raise HTTPException(503, detail="Performance service not available")
    return s


def _validate_timeframe(tf: str) -> str:
    if tf not in _VALID_TIMEFRAMES:
        raise HTTPException(422, detail=f"timeframe must be one of {sorted(_VALID_TIMEFRAMES)}")
    return tf


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
