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


def test_live_returns_payload_and_degraded():
    svc = MagicMock()
    svc.compute_live = AsyncMock(return_value={
        "positions": [], "account_tiles": [], "sector_concentration": [], "degraded": True,
    })
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/live?scope=all")
    assert r.status_code == 200
    assert r.json()["degraded"] is True


def test_live_service_missing_503():
    app = FastAPI()
    app.include_router(perf_router, prefix="/api/v1")
    client = TestClient(app)
    r = client.get("/api/v1/performance/live?scope=all")
    assert r.status_code == 503


def test_cursor_codec_round_trips_including_null_sort_value():
    # Regression: id is a UUID string; sort_value may be None (the NULLS-LAST tail). Both
    # must survive encode->decode, and the encoded form must be a JSON-safe opaque string.
    # _decode_cursor validates the value against the sort mode, so decode with the matching
    # sort (net_pnl -> numeric/None, closed_at -> ISO string).
    from backend.routers.performance import _encode_cursor, _decode_cursor

    for cur, sort in [((5.0, "11111111-1111-1111-1111-111111111111"), "net_pnl"),
                      ((None, "22222222-2222-2222-2222-222222222222"), "net_pnl"),
                      (("2026-05-01T00:00:00+00:00", "33333333-3333-3333-3333-333333333333"),
                       "closed_at")]:
        enc = _encode_cursor(cur)
        assert isinstance(enc, str)
        assert list(cur) == list(_decode_cursor(enc, sort))
    assert _encode_cursor(None) is None
    assert _decode_cursor(None) is None


def test_cursor_encode_rejects_non_finite_sort_value():
    # A non-finite sort value would emit invalid JSON (-Infinity) the browser can't parse.
    # allow_nan=False must make this fail loudly here instead of shipping a broken cursor.
    import pytest
    from backend.routers.performance import _encode_cursor
    with pytest.raises(ValueError):
        _encode_cursor((float("-inf"), "44444444-4444-4444-4444-444444444444"))


def test_trades_page_invalid_cursor_422():
    svc = MagicMock()
    svc.compute_trades_page = AsyncMock(return_value={"rows": [], "cursor": None, "has_more": False})
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/trades?scope=all&timeframe=ALL&cursor=not-valid-base64!!")
    assert r.status_code == 422


def test_trades_page_garbage_cursor_returns_422_not_500():
    # A base64/JSON-VALID cursor with a non-UUID id (or non-numeric sort value) must be
    # rejected as 422 by the decoder, never reach the DB layer, and never 500.
    import base64
    import json as _json
    svc = MagicMock()
    svc.compute_trades_page = AsyncMock(return_value={"rows": [], "cursor": None, "has_more": False})
    client = TestClient(_app(svc))
    for payload in ([5.0, "not-a-uuid"], [True, "11111111-1111-1111-1111-111111111111"],
                    ["x", "11111111-1111-1111-1111-111111111111"], [5.0, 123]):
        cur = base64.urlsafe_b64encode(_json.dumps(payload).encode()).decode()
        r = client.get(f"/api/v1/performance/trades?scope=all&timeframe=ALL&cursor={cur}")
        assert r.status_code == 422, f"expected 422 for {payload}, got {r.status_code}"


def test_trades_page_invalid_dir_422():
    svc = MagicMock()
    client = TestClient(_app(svc))
    r = client.get("/api/v1/performance/trades?scope=all&timeframe=ALL&dir=sideways")
    assert r.status_code == 422
