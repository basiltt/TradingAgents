"""Integration tests for the signal analytics API router (Task 12)."""

import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from backend.routers.signal_analytics import router, set_service


@pytest.fixture
def mock_service():
    svc = AsyncMock()
    svc.get_summary.return_value = {
        "total_trades": 50,
        "win_rate": 0.52,
        "avg_pnl_pct": 0.3,
        "total_pnl": 150.0,
        "avg_hold_minutes": 90,
        "current_streak": "3W",
        "active_alerts": 1,
    }
    svc.get_rolling_win_rate.return_value = [
        {"date": "2026-05-01T00:00:00Z", "win_rate": 0.55, "trade_number": 20}
    ]
    svc.get_calibration_curve.return_value = [
        {"tier": "high", "total": 20, "wins": 12, "win_rate": 0.6}
    ]
    svc.get_benchmark_comparison.return_value = [
        {
            "trade_number": 1,
            "date": "2026-05-01T00:00:00Z",
            "system_pnl": 1.5,
            "buy_and_hold": 0.8,
            "random_expected": 0.0,
        }
    ]
    svc.get_regime_breakdown.return_value = [
        {
            "regime": "trending_up",
            "total": 15,
            "wins": 10,
            "win_rate": 0.67,
            "avg_pnl_pct": 1.2,
        }
    ]
    svc.get_current_regimes.return_value = [
        {"symbol": "BTCUSDT", "regime": "trending_up"}
    ]
    svc.get_decay_alerts.return_value = [
        {
            "id": 1,
            "alert_type": "losing_streak",
            "severity": "warning",
            "message": "5 losses",
        }
    ]
    svc.acknowledge_alert.return_value = True
    svc.get_performance_trades.return_value = {"total": 0, "trades": []}
    return svc


@pytest.fixture
def app(mock_service):
    application = FastAPI()
    application.include_router(router)
    set_service(mock_service)
    return application


@pytest.mark.asyncio
async def test_summary_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_trades"] == 50
    assert data["win_rate"] == 0.52
    assert data["avg_pnl_pct"] == 0.3
    assert data["total_pnl"] == 150.0
    assert data["current_streak"] == "3W"
    assert data["active_alerts"] == 1


@pytest.mark.asyncio
async def test_win_rate_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/win-rate")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["win_rate"] == 0.55


@pytest.mark.asyncio
async def test_calibration_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/calibration")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["tier"] == "high"
    assert data[0]["win_rate"] == 0.6


@pytest.mark.asyncio
async def test_benchmarks_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/benchmarks")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["system_pnl"] == 1.5


@pytest.mark.asyncio
async def test_regime_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/regime")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["regime"] == "trending_up"
    assert data[0]["win_rate"] == 0.67


@pytest.mark.asyncio
async def test_decay_alerts_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/decay-alerts")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["id"] == 1
    assert data[0]["alert_type"] == "losing_streak"


@pytest.mark.asyncio
async def test_acknowledge_alert(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/signal-analytics/decay-alerts/1/acknowledge")
    assert response.status_code == 200
    data = response.json()
    assert data["acknowledged"] is True
    assert data["alert_id"] == 1
    mock_service.acknowledge_alert.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_acknowledge_nonexistent_alert(app, mock_service):
    mock_service.acknowledge_alert.return_value = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/signal-analytics/decay-alerts/999/acknowledge")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trades_endpoint(app, mock_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/signal-analytics/trades")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["trades"] == []
