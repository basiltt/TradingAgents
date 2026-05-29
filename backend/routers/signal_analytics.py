"""Signal analytics router — dashboard KPIs, charts, and alert management."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signal-analytics", tags=["signal-analytics"])

_service = None


def set_service(svc) -> None:
    """Inject the SignalAnalyticsService instance at startup.

    Args:
        svc: Configured SignalAnalyticsService instance.
    """
    global _service
    _service = svc


def _get_service():
    if _service is None:
        raise HTTPException(503, detail="Signal analytics service not available")
    return _service


# ---------------------------------------------------------------------------
# Summary / KPIs
# ---------------------------------------------------------------------------


@router.get("/summary")
async def get_summary(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
):
    """Return high-level performance KPIs (win rate, PnL, streak, active alerts)."""
    svc = _get_service()
    return await svc.get_summary(account_id=account_id, start_date=start_date, end_date=end_date)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


@router.get("/win-rate")
async def get_rolling_win_rate(
    account_id: Optional[str] = Query(None),
    window: int = Query(20, ge=1, le=500, description="Rolling window size in trades"),
):
    """Return rolling win-rate series for the win-rate chart."""
    svc = _get_service()
    return await svc.get_rolling_win_rate(account_id=account_id, window=window)


@router.get("/calibration")
async def get_calibration_curve(
    account_id: Optional[str] = Query(None),
):
    """Return win rate per confidence tier for the calibration chart."""
    svc = _get_service()
    return await svc.get_calibration_curve(account_id=account_id)


@router.get("/benchmarks")
async def get_benchmark_comparison(
    account_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
):
    """Return cumulative PnL curves for system, buy-and-hold, and random-entry."""
    svc = _get_service()
    return await svc.get_benchmark_comparison(
        account_id=account_id, start_date=start_date, end_date=end_date
    )


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------


@router.get("/regime")
async def get_regime_breakdown(
    account_id: Optional[str] = Query(None),
):
    """Return win rate and average PnL grouped by market regime at entry."""
    svc = _get_service()
    return await svc.get_regime_breakdown(account_id=account_id)


@router.get("/regime/current")
async def get_current_regimes():
    """Return the most recent regime snapshot for each symbol."""
    svc = _get_service()
    return await svc.get_current_regimes()


# ---------------------------------------------------------------------------
# Decay alerts
# ---------------------------------------------------------------------------


@router.get("/decay-alerts")
async def get_decay_alerts(
    acknowledged: bool = Query(False, description="Include acknowledged alerts"),
):
    """Return decay alerts filtered by acknowledgement status."""
    svc = _get_service()
    return await svc.get_decay_alerts(acknowledged=acknowledged)


@router.post("/decay-alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    """Mark a decay alert as acknowledged.  Returns 404 if alert not found."""
    svc = _get_service()
    updated = await svc.acknowledge_alert(alert_id)
    if not updated:
        raise HTTPException(404, detail="Alert not found")
    return {"acknowledged": True, "alert_id": alert_id}


# ---------------------------------------------------------------------------
# Trade list
# ---------------------------------------------------------------------------


@router.get("/trades")
async def get_performance_trades(
    account_id: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    confidence_tier: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
    is_win: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200, description="Max rows to return (capped at 200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """Return a paginated, filtered list of signal_performance rows."""
    svc = _get_service()
    return await svc.get_performance_trades(
        account_id=account_id,
        symbol=symbol,
        confidence_tier=confidence_tier,
        regime=regime,
        is_win=is_win,
        limit=limit,
        offset=offset,
    )
