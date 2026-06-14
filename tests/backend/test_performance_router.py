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


def test_trades_breakdown_returns_payload():
    svc = MagicMock()
    svc.compute_breakdowns_for = AsyncMock(return_value={
        "by_symbol": [], "by_strategy": [], "by_close_reason": [],
        "pnl_distribution": [], "hold_time_buckets": [],
        "meta": {"strategy_legacy_approximate": False},
    })
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/trades-breakdown?scope=all&timeframe=1M")
    assert r.status_code == 200
    assert "by_symbol" in r.json()


def test_trades_breakdown_unknown_timeframe_422():
    svc = MagicMock()
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/trades-breakdown?scope=all&timeframe=ZZ")
    assert r.status_code == 422


def test_trades_page_returns_rows_and_cursor():
    svc = MagicMock()
    svc.compute_trades_page = AsyncMock(return_value={
        "rows": [{"id": "t1", "symbol": "BTCUSDT", "side": "Buy", "net_pnl": 5.0,
                  "net_pnl_pct": 5.0, "close_reason": "take_profit",
                  "opened_at": None, "closed_at": None, "hold_hours": None}],
        "cursor": (5.0, "t1"), "has_more": True,
    })
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/trades?scope=all&timeframe=ALL")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["id"] == "t1"
    assert body["has_more"] is True
    # the internal tuple cursor is encoded to an opaque string for the client
    assert isinstance(body["cursor"], str)
