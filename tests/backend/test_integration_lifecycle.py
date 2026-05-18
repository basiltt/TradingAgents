"""Integration tests — full request lifecycle through ASGI stack.

Validates middleware chain (CORS, CSP, CSRF, observability, rate limiting),
service layer, and database persistence work together correctly.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app():
    os.environ.setdefault(
        "DATABASE_URL",
        os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
        ),
    )
    os.environ.setdefault("ACCOUNTS_ENCRYPTION_KEY", "")
    from backend.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


XHR = {"X-Requested-With": "XMLHttpRequest"}


class TestSecurityHeadersIntegration:
    """Verify all security headers propagate through the full middleware chain."""

    @pytest.mark.asyncio
    async def test_all_security_headers_present(self, client):
        resp = await client.get("/api/v1/healthz")
        assert resp.status_code == 200
        assert "content-security-policy" in resp.headers
        assert "x-content-type-options" in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "x-frame-options" in resp.headers
        assert "x-correlation-id" in resp.headers

    @pytest.mark.asyncio
    async def test_correlation_id_unique_per_request(self, client):
        r1 = await client.get("/api/v1/healthz")
        r2 = await client.get("/api/v1/healthz")
        cid1 = r1.headers["x-correlation-id"]
        cid2 = r2.headers["x-correlation-id"]
        assert cid1 != cid2
        assert len(cid1) == 8

    @pytest.mark.asyncio
    async def test_csrf_blocks_post_without_header(self, client):
        resp = await client.post("/api/v1/config", json={})
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == "CSRF_REQUIRED"

    @pytest.mark.asyncio
    async def test_csrf_allows_post_with_header(self, client):
        resp = await client.patch(
            "/api/v1/config",
            json={"overrides": {}},
            headers=XHR,
        )
        assert resp.status_code in (200, 422)


class TestObservabilityIntegration:
    """Verify metrics endpoint reflects actual request activity."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint_accessible(self, client):
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text
        assert "process_uptime_seconds" in resp.text

    @pytest.mark.asyncio
    async def test_metrics_increment_after_requests(self, client):
        await client.get("/api/v1/healthz")
        await client.get("/api/v1/healthz")
        resp = await client.get("/metrics")
        text = resp.text
        assert 'path="/api/v1/healthz"' in text


class TestHealthEndpoints:
    """Verify health checks report correct system state."""

    @pytest.mark.asyncio
    async def test_healthz_liveness(self, client):
        resp = await client.get("/api/v1/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    @pytest.mark.asyncio
    async def test_health_readiness(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["db"] == "ok"
        assert "analyses_active" in data
        assert "coingecko" in data


class TestConfigServiceIntegration:
    """Verify config CRUD persists through the full stack to the database."""

    @pytest.mark.asyncio
    async def test_config_roundtrip(self, client):
        resp = await client.patch(
            "/api/v1/config",
            json={"overrides": {"output_language": "Spanish"}},
            headers=XHR,
        )
        assert resp.status_code == 200

        resp = await client.get("/api/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved"]["output_language"] == "Spanish"

        # Reset
        await client.patch(
            "/api/v1/config",
            json={"overrides": {"output_language": "English"}},
            headers=XHR,
        )


class TestAnalysisServiceIntegration:
    """Verify analysis lifecycle through the API layer."""

    @pytest.mark.asyncio
    async def test_list_analyses(self, client):
        resp = await client.get("/api/v1/analysis")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_nonexistent_analysis(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/analysis/{fake_id}")
        assert resp.status_code == 404


class TestContentSizeLimit:
    """Verify oversized requests are rejected."""

    @pytest.mark.asyncio
    async def test_oversized_body_rejected(self, client):
        huge = "x" * (2 * 1024 * 1024)
        resp = await client.post(
            "/api/v1/config",
            content=huge,
            headers={**XHR, "Content-Type": "application/json", "Content-Length": str(len(huge))},
        )
        assert resp.status_code == 413
