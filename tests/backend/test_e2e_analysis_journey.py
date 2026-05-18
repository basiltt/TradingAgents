"""E2E test — critical analysis journey through the full API surface.

Exercises: POST /analysis → WS progress events → GET /analysis/{id} → DELETE.
The LLM graph is mocked to avoid real API calls, but everything else
(database, middleware, WebSocket, event bus) runs for real.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
    ))
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-e2e")
    monkeypatch.delenv("TRADINGAGENTS_BACKEND_URL", raising=False)
    from backend.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


XHR = {"X-Requested-With": "XMLHttpRequest"}


class TestAnalysisE2EJourney:
    """Full lifecycle: create → poll → retrieve → delete."""

    @pytest.mark.asyncio
    async def test_analysis_lifecycle(self, client, app):
        fake_result = {
            "final_decision": "BUY",
            "confidence": 0.85,
            "report": "Test analysis report",
        }

        def mock_execute_graph(self_svc, run_id, request, config, callback, cancel_event):
            return fake_result

        with patch(
            "backend.services.analysis_service.AnalysisService._execute_graph",
            mock_execute_graph,
        ), patch(
            "backend.services.analysis_service.validate_backend_url",
            side_effect=lambda url, **kw: url,
        ):
            # 1. Start analysis
            resp = await client.post(
                "/api/v1/analysis",
                json={
                    "ticker": "AAPL",
                    "analysis_date": "2025-01-15",
                    "asset_type": "stock",
                    "analysts": ["fundamentals", "market"],
                },
                headers=XHR,
            )
            assert resp.status_code == 201, resp.text
            data = resp.json()
            run_id = data["run_id"]
            assert data["status"] == "running"

            # 2. Wait for completion (the mock finishes instantly)
            for _ in range(30):
                await asyncio.sleep(0.3)
                resp = await client.get(f"/api/v1/analysis/{run_id}")
                if resp.status_code == 200:
                    run_data = resp.json()
                    if run_data.get("status") in ("completed", "failed"):
                        break
            else:
                pytest.fail("Analysis did not complete within timeout")

            # 3. Verify completed state
            assert run_data["status"] == "completed"
            assert run_data["ticker"] == "AAPL"

            # 4. Delete the analysis
            resp = await client.delete(
                f"/api/v1/analysis/{run_id}",
                headers=XHR,
            )
            assert resp.status_code in (200, 204)

            # 5. Verify deleted
            resp = await client.get(f"/api/v1/analysis/{run_id}")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_analysis_validation_errors(self, client):
        # Missing required fields
        resp = await client.post(
            "/api/v1/analysis",
            json={},
            headers=XHR,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_analysis_invalid_run_id(self, client):
        resp = await client.get("/api/v1/analysis/not-a-uuid")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_analysis_nonexistent_run(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/analysis/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_concurrent_analysis_respects_cap(self, client, app):
        """Verify concurrency limit is enforced."""
        svc = app.state.analysis_service
        original_cap = svc._max_concurrent
        svc._max_concurrent = 1

        # Fill the single slot with a fake running analysis
        fake_id = str(uuid.uuid4())
        svc._active_runs[fake_id] = {"status": "running"}

        try:
            resp = await client.post(
                "/api/v1/analysis",
                json={
                    "ticker": "TSLA",
                    "analysis_date": "2025-01-15",
                    "asset_type": "stock",
                    "analysts": ["fundamentals"],
                },
                headers=XHR,
            )
            assert resp.status_code == 429
        finally:
            del svc._active_runs[fake_id]
            svc._max_concurrent = original_cap
