"""Tests for the backtest REST router (Task 5.3) via FastAPI TestClient."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def app_client():
    """A FastAPI app with just the backtest router and a mocked service."""
    from fastapi import FastAPI
    from backend.routers.backtest import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    svc = MagicMock()
    svc.create_backtest = AsyncMock(return_value="run-123")
    svc.get_backtest = AsyncMock()
    svc.list_backtests = AsyncMock(return_value=[])
    svc.cancel_backtest = AsyncMock(return_value=True)
    svc.delete_backtest = AsyncMock(return_value=True)
    svc.compare_backtests = AsyncMock(return_value={"runs": []})
    svc.get_backtest_trades = AsyncMock(return_value={"trades": [], "total": 0, "page": 1})
    svc.cache_status = AsyncMock(return_value={"symbols_total": 1, "symbols_cached": 1,
                                               "symbols_with_gaps": [], "ready": True})
    svc.warmup_cache = AsyncMock(return_value={"cached": 1, "fetched": 0, "failed": 0,
                                               "symbols_with_gaps": []})
    svc.has_free_slot = MagicMock(return_value=True)
    app.state.backtest_service = svc

    from fastapi.testclient import TestClient
    return TestClient(app), svc


def _valid_create_body():
    return {
        "starting_capital": 10000.0,
        "date_range_start": "2026-01-01T00:00:00Z",
        "date_range_end": "2026-01-10T00:00:00Z",
        "scan_source": {"mode": "date_range"},
        "leverage": 20,
        "take_profit_pct": 150.0,
        "stop_loss_pct": 100.0,
    }


class TestCreateEndpoint:
    def test_create_returns_201(self, app_client):
        client, svc = app_client
        resp = client.post("/api/v1/backtest", json=_valid_create_body())
        assert resp.status_code == 201
        assert resp.json()["run_id"] == "run-123"
        svc.create_backtest.assert_awaited_once()

    def test_create_invalid_body_returns_422(self, app_client):
        client, svc = app_client
        bad = _valid_create_body()
        bad["starting_capital"] = -5  # gt=0 violation
        resp = client.post("/api/v1/backtest", json=bad)
        assert resp.status_code == 422

    def test_create_validation_error_returns_422(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestValidationError
        svc.create_backtest = AsyncMock(side_effect=BacktestValidationError("too big"))
        resp = client.post("/api/v1/backtest", json=_valid_create_body())
        assert resp.status_code == 422
        assert "too big" in resp.json()["detail"]

    def test_create_returns_503_when_no_slot(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestBusyError
        svc.create_backtest = AsyncMock(side_effect=BacktestBusyError("busy"))
        resp = client.post("/api/v1/backtest", json=_valid_create_body())
        assert resp.status_code == 503

    def test_create_returns_429_when_rate_limited(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestRateLimitError
        svc.create_backtest = AsyncMock(side_effect=BacktestRateLimitError("slow down"))
        resp = client.post("/api/v1/backtest", json=_valid_create_body())
        assert resp.status_code == 429


class TestListEndpoint:
    def test_list_returns_200(self, app_client):
        client, svc = app_client
        svc.list_backtests = AsyncMock(return_value=[
            {"id": "a", "status": "completed", "config": {}, "scan_source": {},
             "progress_pct": 100, "error_message": None, "started_at": None,
             "completed_at": None, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        ])
        resp = client.get("/api/v1/backtest")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestGetEndpoint:
    def test_get_returns_200(self, app_client):
        client, svc = app_client
        svc.get_backtest = AsyncMock(return_value={
            "id": "run-1", "status": "completed", "config": {}, "scan_source": {},
            "progress_pct": 100, "error_message": None, "started_at": None,
            "completed_at": None, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "results": {"metrics": {}, "equity_curve": [], "summary": {}, "warnings": []},
        })
        resp = client.get("/api/v1/backtest/11111111-1111-1111-1111-111111111111")
        assert resp.status_code == 200
        assert resp.json()["id"] == "run-1"

    def test_get_nonexistent_returns_404(self, app_client):
        client, svc = app_client
        svc.get_backtest = AsyncMock(return_value=None)
        resp = client.get("/api/v1/backtest/22222222-2222-2222-2222-222222222222")
        assert resp.status_code == 404

    def test_get_non_uuid_returns_422(self, app_client):
        client, svc = app_client
        # A non-UUID path segment must 422, not 500 (asyncpg DataError)
        resp = client.get("/api/v1/backtest/not-a-uuid")
        assert resp.status_code == 422
        svc.get_backtest.assert_not_awaited()


class TestTradesEndpoint:
    def test_trades_returns_200_paginated(self, app_client):
        client, svc = app_client
        svc.get_backtest_trades = AsyncMock(return_value={"trades": [], "total": 0, "page": 1})
        resp = client.get("/api/v1/backtest/11111111-1111-1111-1111-111111111111/trades?page=1&limit=50")
        assert resp.status_code == 200
        body = resp.json()
        assert "trades" in body and "total" in body and "page" in body


class TestCancelEndpoint:
    def test_cancel_returns_200(self, app_client):
        client, svc = app_client
        svc.cancel_backtest = AsyncMock(return_value=True)
        resp = client.post("/api/v1/backtest/11111111-1111-1111-1111-111111111111/cancel")
        assert resp.status_code == 200

    def test_cancel_nonexistent_returns_404(self, app_client):
        client, svc = app_client
        svc.cancel_backtest = AsyncMock(return_value=False)
        resp = client.post("/api/v1/backtest/22222222-2222-2222-2222-222222222222/cancel")
        assert resp.status_code == 404

    def test_cancel_terminal_returns_409(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestConflictError
        svc.cancel_backtest = AsyncMock(side_effect=BacktestConflictError("already completed"))
        resp = client.post("/api/v1/backtest/11111111-1111-1111-1111-111111111111/cancel")
        assert resp.status_code == 409


class TestDeleteEndpoint:
    def test_delete_returns_204(self, app_client):
        client, svc = app_client
        svc.delete_backtest = AsyncMock(return_value=True)
        resp = client.delete("/api/v1/backtest/11111111-1111-1111-1111-111111111111")
        assert resp.status_code == 204

    def test_delete_nonexistent_returns_404(self, app_client):
        client, svc = app_client
        svc.delete_backtest = AsyncMock(return_value=False)
        resp = client.delete("/api/v1/backtest/22222222-2222-2222-2222-222222222222")
        assert resp.status_code == 404

    def test_delete_running_returns_409(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestConflictError
        svc.delete_backtest = AsyncMock(side_effect=BacktestConflictError("running"))
        resp = client.delete("/api/v1/backtest/11111111-1111-1111-1111-111111111111")
        assert resp.status_code == 409


class TestCompareEndpoint:
    _UUIDS = ("11111111-1111-1111-1111-111111111111",
              "22222222-2222-2222-2222-222222222222")

    def test_compare_returns_200(self, app_client):
        client, svc = app_client
        svc.compare_backtests = AsyncMock(return_value={"runs": [{"id": "a"}, {"id": "b"}]})
        a, b = self._UUIDS
        resp = client.get(f"/api/v1/backtest/compare?run_ids={a}&run_ids={b}")
        assert resp.status_code == 200
        assert len(resp.json()["runs"]) == 2

    def test_compare_invalid_count_returns_422(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestValidationError
        svc.compare_backtests = AsyncMock(side_effect=BacktestValidationError("need 2-4"))
        # single VALID UUID → passes UUID check, then service raises count error
        resp = client.get(f"/api/v1/backtest/compare?run_ids={self._UUIDS[0]}")
        assert resp.status_code == 422

    def test_compare_non_uuid_returns_422(self, app_client):
        client, svc = app_client
        # A malformed run_id must 422 (not 500) before reaching the service
        resp = client.get("/api/v1/backtest/compare?run_ids=foo&run_ids=bar")
        assert resp.status_code == 422
        svc.compare_backtests.assert_not_awaited()

    def test_compare_missing_run_returns_404(self, app_client):
        client, svc = app_client
        from backend.services.backtest_service import BacktestNotFoundError
        svc.compare_backtests = AsyncMock(side_effect=BacktestNotFoundError("not found: b"))
        a, b = self._UUIDS
        resp = client.get(f"/api/v1/backtest/compare?run_ids={a}&run_ids={b}")
        assert resp.status_code == 404


class TestCacheStatusEndpoint:
    def test_cache_status_returns_200(self, app_client):
        client, svc = app_client
        resp = client.get(
            "/api/v1/backtest-cache/status"
            "?symbols=BTCUSDT&symbols=ETHUSDT&interval=5m"
            "&start=2026-01-01T00:00:00Z&end=2026-01-02T00:00:00Z"
        )
        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    def test_cache_status_bad_dates_returns_422(self, app_client):
        client, svc = app_client
        resp = client.get(
            "/api/v1/backtest-cache/status?symbols=BTCUSDT&start=not-a-date&end=also-bad"
        )
        assert resp.status_code == 422

    def test_warmup_cache_returns_202(self, app_client):
        client, svc = app_client
        resp = client.post(
            "/api/v1/backtest-cache/warmup"
            "?symbols=BTCUSDT&symbols=ETHUSDT&interval=5m"
            "&start=2026-01-01T00:00:00Z&end=2026-01-02T00:00:00Z"
        )
        assert resp.status_code == 202
        svc.warmup_cache.assert_awaited_once()


class TestRouterWiring:
    """Task 5.4 smoke test — router registered with expected routes."""

    def test_router_exposes_expected_routes(self):
        from backend.routers.backtest import router
        paths = {r.path for r in router.routes}
        assert "/backtest" in paths
        assert "/backtest/{run_id}" in paths
        assert "/backtest/{run_id}/trades" in paths
        assert "/backtest/{run_id}/cancel" in paths
        assert "/backtest/compare" in paths

    def test_service_unavailable_returns_503(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.routers.backtest import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        # No backtest_service on app.state → 503
        app.state.backtest_service = None
        client = TestClient(app)
        resp = client.get("/api/v1/backtest")
        assert resp.status_code == 503

