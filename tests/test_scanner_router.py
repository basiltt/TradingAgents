"""Tests for backend.routers.scanner — Phase 1 unit tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os


class TestValidateScanId:
    def test_valid_uuid(self):
        from backend.routers.scanner import _validate_scan_id
        _validate_scan_id("550e8400-e29b-41d4-a716-446655440000")

    def test_invalid_uuid_raises(self):
        from backend.routers.scanner import _validate_scan_id
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_scan_id("not-a-uuid")
        assert exc_info.value.status_code == 400


class TestScannerRouterEndpoints:
    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from backend.routers.scanner import router
        app = FastAPI()
        app.include_router(router)

        config_service = MagicMock()
        config_service.get_config.return_value = {"resolved": {"llm_provider": "openai"}}
        scanner_service = AsyncMock()
        app.state.config_service = config_service
        app.state.scanner_service = scanner_service
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_list_scans(self, client, app):
        app.state.scanner_service.list_scans.return_value = [{"scan_id": "s1"}]
        resp = client.get("/scanner")
        assert resp.status_code == 200
        assert resp.json()["scans"] == [{"scan_id": "s1"}]

    def test_get_scan_valid(self, client, app):
        app.state.scanner_service.get_scan.return_value = {"scan_id": "550e8400-e29b-41d4-a716-446655440000"}
        resp = client.get("/scanner/550e8400-e29b-41d4-a716-446655440000")
        assert resp.status_code == 200

    def test_get_scan_invalid_uuid(self, client):
        resp = client.get("/scanner/bad-id")
        assert resp.status_code == 400

    def test_get_scan_not_found(self, client, app):
        app.state.scanner_service.get_scan.return_value = None
        resp = client.get("/scanner/550e8400-e29b-41d4-a716-446655440000")
        assert resp.status_code == 404

    def test_cancel_scan(self, client, app):
        app.state.scanner_service.cancel_scan.return_value = True
        resp = client.post("/scanner/550e8400-e29b-41d4-a716-446655440000/cancel")
        assert resp.status_code == 200

    def test_cancel_scan_not_found(self, client, app):
        app.state.scanner_service.cancel_scan.return_value = False
        resp = client.post("/scanner/550e8400-e29b-41d4-a716-446655440000/cancel")
        assert resp.status_code == 404

    def test_start_scan_missing_api_key(self, client, app):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            resp = client.post("/scanner", json={
                "analysis_date": "2025-01-10",
            })
        assert resp.status_code == 422

    def test_start_scan_success(self, client, app):
        app.state.scanner_service.start_scan.return_value = "scan-123"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
            resp = client.post("/scanner", json={
                "analysis_date": "2025-01-10",
            })
        assert resp.status_code == 201
        assert resp.json()["scan_id"] == "scan-123"

    def test_start_scan_busy(self, client, app):
        from backend.services.scanner_service import ScannerBusyError
        app.state.scanner_service.start_scan.side_effect = ScannerBusyError("busy")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}):
            resp = client.post("/scanner", json={
                "analysis_date": "2025-01-10",
            })
        assert resp.status_code == 409
