"""Performance analytics router — snapshots, charts, and KPI endpoints."""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.services.bybit_client import BybitAPIError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics"])

_VALID_PERIODS = {
    "1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H",
    "1D", "3D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL",
}
_VALID_ACCOUNT_TYPES = {"demo", "live"}


def _validate_account_type(account_type: str | None) -> str | None:
    if account_type and account_type not in _VALID_ACCOUNT_TYPES:
        raise HTTPException(422, detail="account_type must be 'demo' or 'live'")
    return account_type


def _validate_date_param(value: str | None, name: str) -> str | None:
    if not value:
        return value
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, detail=f"Invalid {name} format, expected YYYY-MM-DD") from None
    return value


def _get_service(request: Request):
    svc = request.app.state.accounts_service
    if svc is None:
        raise HTTPException(503, detail="Accounts feature disabled — set ACCOUNTS_ENCRYPTION_KEY")
    return svc


def _validate_account_id(account_id: str) -> str:
    try:
        _uuid.UUID(account_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid account ID format") from None
    return account_id


def _resolve_dates(
    start_date: str | None, end_date: str | None, period: str,
) -> tuple[str, str]:
    if start_date and end_date:
        try:
            s = date.fromisoformat(start_date)
            e = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(422, detail="Invalid date format, expected YYYY-MM-DD") from None
        if s > e:
            raise HTTPException(422, detail="start_date must be before or equal to end_date")
        return start_date, end_date

    if (start_date and not end_date) or (end_date and not start_date):
        raise HTTPException(422, detail="Both start_date and end_date must be provided together")

    if period not in _VALID_PERIODS:
        raise HTTPException(422, detail=f"Invalid period. Must be one of: {', '.join(sorted(_VALID_PERIODS))}")

    today = datetime.now(timezone.utc).date()
    if period == "YTD":
        return str(date(today.year, 1, 1)), str(today)
    if period == "ALL":
        return str(date(2020, 1, 1)), str(today)
    if period in ("1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H", "1D"):
        return str(today), str(today)
    periods = {
        "3D": timedelta(days=3),
        "1W": timedelta(days=7),
        "1M": timedelta(days=30),
        "3M": timedelta(days=90),
        "6M": timedelta(days=180),
        "1Y": timedelta(days=365),
    }
    return str(today - periods[period]), str(today)


@router.post("/accounts/{account_id}/snapshots")
async def take_snapshot(request: Request, account_id: str):
    _validate_account_id(account_id)
    svc = _get_service(request)
    try:
        result = await svc.take_snapshot(account_id)
        return result
    except ValueError as e:
        msg = str(e)
        if "rate limit" in msg.lower():
            return JSONResponse({"detail": "Too many snapshots — try again in 30 seconds", "code": "RATE_LIMITED"}, 429)
        if "inactive" in msg.lower():
            return JSONResponse({"detail": "Account is inactive", "code": "ACCOUNT_INACTIVE"}, 409)
        return JSONResponse({"detail": "Account not found", "code": "NOT_FOUND"}, 404)
    except BybitAPIError:
        return JSONResponse({"detail": "Exchange API error", "code": "BYBIT_ERROR"}, 502)


@router.post("/snapshots/all")
async def take_all_snapshots(request: Request):
    svc = _get_service(request)
    results = await svc.take_all_snapshots()
    await svc.take_all_hf_snapshots()
    return {"snapshots": results, "count": len(results)}


_SUB_DAY_PERIODS = {"1m", "5m", "15m", "30m", "1H", "2H", "6H", "12H"}
_SUB_DAY_DELTAS = {
    "1m": timedelta(minutes=30),
    "5m": timedelta(hours=2),
    "15m": timedelta(hours=6),
    "30m": timedelta(hours=12),
    "1H": timedelta(hours=24),
    "2H": timedelta(hours=48),
    "6H": timedelta(days=7),
    "12H": timedelta(days=14),
}


def _is_sub_day(period: str) -> bool:
    return period in _SUB_DAY_PERIODS


def _resolve_hf_since(period: str) -> datetime:
    delta = _SUB_DAY_DELTAS.get(period, timedelta(minutes=1))
    return datetime.now(timezone.utc) - delta


@router.get("/accounts/{account_id}/snapshots")
async def get_snapshots(
    request: Request,
    account_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    period: str = Query("1M"),
):
    _validate_account_id(account_id)
    svc = _get_service(request)
    if _is_sub_day(period):
        since = _resolve_hf_since(period)
        return await svc.get_hf_snapshots(account_id, since)
    sd, ed = _resolve_dates(start_date, end_date, period)
    return await svc.get_snapshots(account_id, sd, ed)


@router.get("/accounts/{account_id}/analytics")
async def get_analytics(
    request: Request,
    account_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    period: str = Query("1M"),
):
    _validate_account_id(account_id)
    svc = _get_service(request)
    if _is_sub_day(period):
        since = _resolve_hf_since(period)
        return await svc.compute_hf_analytics(account_id, since)
    sd, ed = _resolve_dates(start_date, end_date, period)
    return await svc.compute_analytics(account_id, sd, ed)


@router.get("/portfolio/snapshots")
async def get_portfolio_snapshots(
    request: Request,
    start_date: str = Query(None),
    end_date: str = Query(None),
    period: str = Query("1M"),
    account_type: str = Query(None),
):
    svc = _get_service(request)
    _validate_account_type(account_type)
    if _is_sub_day(period):
        since = _resolve_hf_since(period)
        return await svc.get_portfolio_hf_snapshots(since, account_type=account_type)
    sd, ed = _resolve_dates(start_date, end_date, period)
    return await svc.get_portfolio_snapshots(sd, ed, account_type=account_type)


@router.get("/portfolio/analytics")
async def get_portfolio_analytics(
    request: Request,
    start_date: str = Query(None),
    end_date: str = Query(None),
    period: str = Query("1M"),
    account_type: str = Query(None),
):
    svc = _get_service(request)
    _validate_account_type(account_type)
    if _is_sub_day(period):
        since = _resolve_hf_since(period)
        return await svc.compute_portfolio_hf_analytics(since, account_type=account_type)
    sd, ed = _resolve_dates(start_date, end_date, period)
    return await svc.compute_portfolio_analytics(sd, ed, account_type=account_type)


_VALID_CLEANUP_PRESETS = {"1w", "1m", "3m", "6m", "1y", "all"}


def _validate_cleanup_params(preset: str | None, before: str | None, after: str | None) -> None:
    if not preset and not before and not after:
        raise HTTPException(422, detail="At least one of preset, before, or after is required")
    if preset and preset not in _VALID_CLEANUP_PRESETS:
        raise HTTPException(422, detail=f"Invalid preset. Must be one of: {', '.join(sorted(_VALID_CLEANUP_PRESETS))}")
    if before:
        _validate_date_param(before, "before")
    if after:
        _validate_date_param(after, "after")
    if before and after and after > before:
        raise HTTPException(422, detail="after date must be before or equal to before date")


@router.get("/accounts/{account_id}/snapshots/count")
async def count_account_snapshots(
    request: Request,
    account_id: str,
    preset: str = Query(None),
    before: str = Query(None),
    after: str = Query(None),
):
    _validate_account_id(account_id)
    _validate_cleanup_params(preset, before, after)
    svc = _get_service(request)
    try:
        counts = await svc.count_snapshot_data(account_id, preset=preset, before_date=before, after_date=after)
        return {"counts": counts, "total": sum(counts.values())}
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)


@router.delete("/accounts/{account_id}/snapshots/cleanup")
async def cleanup_account_snapshots(
    request: Request,
    account_id: str,
    preset: str = Query(None),
    before: str = Query(None),
    after: str = Query(None),
):
    _validate_account_id(account_id)
    _validate_cleanup_params(preset, before, after)
    svc = _get_service(request)
    try:
        result = await svc.cleanup_snapshot_data(account_id, preset=preset, before_date=before, after_date=after)
        return {"deleted": result, "total": sum(result.values())}
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)


@router.get("/portfolio/snapshots/count")
async def count_portfolio_snapshots(
    request: Request,
    preset: str = Query(None),
    before: str = Query(None),
    after: str = Query(None),
):
    _validate_cleanup_params(preset, before, after)
    svc = _get_service(request)
    try:
        counts = await svc.count_snapshot_data(None, preset=preset, before_date=before, after_date=after)
        return {"counts": counts, "total": sum(counts.values())}
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)


@router.delete("/portfolio/snapshots/cleanup")
async def cleanup_portfolio_snapshots(
    request: Request,
    preset: str = Query(None),
    before: str = Query(None),
    after: str = Query(None),
):
    _validate_cleanup_params(preset, before, after)
    svc = _get_service(request)
    try:
        result = await svc.cleanup_snapshot_data(None, preset=preset, before_date=before, after_date=after)
        return {"deleted": result, "total": sum(result.values())}
    except ValueError as e:
        return JSONResponse({"detail": str(e), "code": "VALIDATION_ERROR"}, 422)
