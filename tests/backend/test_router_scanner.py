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
