"""Tests for scanner router — Phase 2 API tests."""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app(tmp_path):
    import os
    os.environ["TRADINGAGENTS_WEB_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    from backend.main import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


CSRF = {"X-Requested-With": "XMLHttpRequest"}


@pytest.mark.asyncio
async def test_start_scan_success(client):
    with patch(
        "backend.services.scanner_service.ScannerService.start_scan",
        new_callable=AsyncMock,
        return_value="00000000-0000-0000-0000-000000000001",
    ):
        resp = await client.post(
            "/api/v1/scanner",
            json={"analysis_date": "2025-06-01", "provider": "anthropic"},
            headers=CSRF,
        )
    assert resp.status_code == 201
    assert resp.json()["scan_id"] == "00000000-0000-0000-0000-000000000001"
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_start_scan_missing_api_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_BACKEND_URL", raising=False)
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "provider": "openai"},
        headers=CSRF,
    )
    assert resp.status_code == 422
    assert "API key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_start_scan_busy_conflict(client):
    from backend.services.scanner_service import ScannerBusyError

    with patch(
        "backend.services.scanner_service.ScannerService.start_scan",
        new_callable=AsyncMock,
        side_effect=ScannerBusyError("Scanner busy"),
    ):
        resp = await client.post(
            "/api/v1/scanner",
            json={"analysis_date": "2025-06-01", "provider": "anthropic"},
            headers=CSRF,
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_start_scan_csrf_required(client):
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_scans(client):
    with patch(
        "backend.services.scanner_service.ScannerService.list_scans",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get("/api/v1/scanner")
    assert resp.status_code == 200
    assert resp.json()["scans"] == []


@pytest.mark.asyncio
async def test_get_scan_success(client):
    scan_data = {"scan_id": "00000000-0000-0000-0000-000000000001", "status": "done"}
    with patch(
        "backend.services.scanner_service.ScannerService.get_scan",
        new_callable=AsyncMock,
        return_value=scan_data,
    ):
        resp = await client.get("/api/v1/scanner/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


@pytest.mark.asyncio
async def test_get_scan_invalid_id(client):
    resp = await client.get("/api/v1/scanner/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_scan_not_found(client):
    with patch(
        "backend.services.scanner_service.ScannerService.get_scan",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.get("/api/v1/scanner/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_scan_success(client):
    with patch(
        "backend.services.scanner_service.ScannerService.cancel_scan",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = await client.post(
            "/api/v1/scanner/00000000-0000-0000-0000-000000000001/cancel",
            headers=CSRF,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_scan_not_found(client):
    with patch(
        "backend.services.scanner_service.ScannerService.cancel_scan",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = await client.post(
            "/api/v1/scanner/00000000-0000-0000-0000-000000000001/cancel",
            headers=CSRF,
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_scan_invalid_id(client):
    resp = await client.post(
        "/api/v1/scanner/bad-id/cancel",
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_scan_backend_url_skips_key_check(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch(
        "backend.services.scanner_service.ScannerService.start_scan",
        new_callable=AsyncMock,
        return_value="00000000-0000-0000-0000-000000000002",
    ):
        resp = await client.post(
            "/api/v1/scanner",
            json={
                "analysis_date": "2025-06-01",
                "backend_url": "http://ollama:11434",
            },
            headers=CSRF,
        )
    assert resp.status_code == 201


# --------------------------------------------------------------------------- #
# Auto-trade single-flight claim release (Phase 2 review R2 — H1 leak fix)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_auto_trade_not_found_releases_in_flight_claim(client):
    """A 404 (scan not found) must RELEASE the _in_flight_auto_trades claim so the same
    scan_id can be retried — otherwise a validation failure permanently 409-bricks it."""
    from backend.routers.scanner import _in_flight_auto_trades

    sid = "00000000-0000-0000-0000-0000000000aa"
    assert sid not in _in_flight_auto_trades
    resp = await client.post(f"/api/v1/scanner/{sid}/auto-trade", headers=CSRF)
    # 404 (not found) or 503 (no accounts service) — both are validation rejections.
    assert resp.status_code in (404, 503)
    # The claim must have been released (not leaked).
    assert sid not in _in_flight_auto_trades, "in-flight claim leaked on a rejected request"

    # A second request for the same scan is NOT pre-empted by a stale 409.
    resp2 = await client.post(f"/api/v1/scanner/{sid}/auto-trade", headers=CSRF)
    assert resp2.status_code in (404, 503)
    assert resp2.status_code != 409


@pytest.mark.asyncio
async def test_auto_trade_invalid_id_releases_no_claim(client):
    """An invalid scan_id is rejected at validation (400) BEFORE the claim — and must
    never leave a claim behind regardless."""
    from backend.routers.scanner import _in_flight_auto_trades

    resp = await client.post("/api/v1/scanner/bad-id/auto-trade", headers=CSRF)
    assert resp.status_code == 400
    assert "bad-id" not in _in_flight_auto_trades


@pytest.mark.asyncio
async def test_manual_auto_trade_in_flight_409_when_central_slot_held(client):
    """R2/R3: the up-front guard rejects a manual auto-trade with 409 when the central
    single-flight slot is already held by a scheduled tail — so the manual path never
    even reaches the background task / DB write that could clobber the in-flight tail."""
    from backend.services import post_scan_concurrency as _psc
    from backend.routers.scanner import _in_flight_auto_trades

    _psc.reset_for_tests()
    sid = "00000000-0000-0000-0000-0000000000cd"
    assert _psc.try_begin_tail(sid) is True
    try:
        resp = await client.post(f"/api/v1/scanner/{sid}/auto-trade", headers=CSRF)
        assert resp.status_code == 409, "must 409 while the central single-flight is held"
        # No claim leaked on the rejection.
        assert sid not in _in_flight_auto_trades
    finally:
        _psc.end_tail(sid)
        _psc.reset_for_tests()


