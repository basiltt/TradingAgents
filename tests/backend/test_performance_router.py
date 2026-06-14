"""Router tests for /api/v1/performance/overview."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.performance import router as perf_router


def _app(svc):
    app = FastAPI()
    app.state.performance_service = svc
    app.include_router(perf_router, prefix="/api/v1")
    return app


def test_overview_returns_payload():
    svc = MagicMock()
    svc.compute_overview = AsyncMock(return_value={
        "kpis": {"net_pnl": 12.5, "realized_pnl_gross": 14.1, "win_count": 10,
                 "loss_count": 6, "max_consecutive_wins": 4, "max_consecutive_losses": 2,
                 "total_trades": 16},
        "kpis_prev": None, "equity_curve": [], "equity_now": None,
        "drawdown_series": [], "daily_pnl": [], "monthly_pnl": [],
        "meta": {"currency": "USDT", "grouping_tz": "UTC", "trading_days": 0,
                 "starting_equity": 174.0, "return_basis": "recorded_history",
                 "live_equity_available": False,
                 "live_sourced": ["total_equity", "unrealized_pnl", "open_count"],
                 "degraded": True},
    })
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/overview?scope=all&timeframe=ALL")
    assert r.status_code == 200
    assert r.json()["kpis"]["net_pnl"] == 12.5


def test_overview_unknown_timeframe_422():
    svc = MagicMock()
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/overview?scope=all&timeframe=7H")
    assert r.status_code == 422


def test_overview_service_missing_503():
    app = FastAPI()
    app.include_router(perf_router, prefix="/api/v1")
    client = TestClient(app)
    r = client.get("/api/v1/performance/overview?scope=all&timeframe=ALL")
    assert r.status_code == 503
