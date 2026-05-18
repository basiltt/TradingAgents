"""Tests for analysis router — TASK-013."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WEB_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("TRADINGAGENTS_BACKEND_URL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_LLM_PROVIDER", raising=False)
    from backend.main import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


@pytest.mark.asyncio
async def test_start_analysis(client):
    import uuid
    fake_run_id = str(uuid.uuid4())
    with patch(
        "backend.services.analysis_service.AnalysisService.start_analysis",
        return_value=fake_run_id,
    ):
        resp = await client.post(
            "/api/v1/analysis",
            json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "anthropic"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["run_id"] == fake_run_id
        assert data["status"] == "running"


@pytest.mark.asyncio
async def test_start_analysis_concurrency_limit(client):
    from backend.services.analysis_service import ConcurrencyLimitError

    with patch(
        "backend.services.analysis_service.AnalysisService.start_analysis",
        side_effect=ConcurrencyLimitError("limit reached"),
    ):
        resp = await client.post(
            "/api/v1/analysis",
            json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "anthropic"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_start_analysis_value_error(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.start_analysis",
        side_effect=ValueError("bad input"),
    ):
        resp = await client.post(
            "/api/v1/analysis",
            json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "anthropic"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_analysis_success(client):
    run_data = {"run_id": "00000000-0000-0000-0000-000000000001", "status": "done"}
    with patch(
        "backend.services.analysis_service.AnalysisService.get_run",
        return_value=run_data,
    ):
        resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


@pytest.mark.asyncio
async def test_get_report_success(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.get_run",
        return_value={"run_id": "00000000-0000-0000-0000-000000000001"},
    ):
        with patch(
            "backend.services.analysis_service.AnalysisService.get_report",
            return_value="# Report\nBUY SPY",
        ):
            resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000001/report")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_get_report_no_report(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.get_run",
        return_value={"run_id": "00000000-0000-0000-0000-000000000001"},
    ):
        with patch(
            "backend.services.analysis_service.AnalysisService.get_report",
            return_value=None,
        ):
            resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000001/report")
    assert resp.status_code == 404
    assert "Report not available" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_report_run_not_found(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.get_run",
        return_value=None,
    ):
        resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000001/report")
    assert resp.status_code == 404
    assert "Run not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_snapshot_success(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.get_snapshot",
        return_value={"events": []},
    ):
        resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000001/snapshot")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_analysis_success(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.cancel_analysis",
        return_value=True,
    ):
        resp = await client.post(
            "/api/v1/analysis/00000000-0000-0000-0000-000000000001/cancel",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_delete_analysis_success(client):
    with patch(
        "backend.services.analysis_service.AnalysisService.delete_run",
        return_value=True,
    ):
        resp = await client.delete(
            "/api/v1/analysis/00000000-0000-0000-0000-000000000001",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_start_analysis_missing_csrf(client):
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_start_analysis_missing_api_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "openai"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 422
    assert "API key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_analyses(client):
    resp = await client.get("/api/v1/analysis")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_analysis_invalid_run_id(client):
    resp = await client.get("/api/v1/analysis/nonexistent-id")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_analysis_not_found(client):
    resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_analysis_csrf_required(client):
    resp = await client.post("/api/v1/analysis/00000000-0000-0000-0000-000000000000/cancel")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_report_download_content_type(client):
    import asyncio
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", return_value={"final_trade_decision": "BUY SPY"}):
        start_resp = await client.post(
            "/api/v1/analysis",
            json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "anthropic"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        run_id = start_resp.json()["run_id"]
        await asyncio.sleep(0.5)

        resp = await client.get(f"/api/v1/analysis/{run_id}/report")
        if resp.status_code == 200:
            assert "text/markdown" in resp.headers.get("content-type", "")
            assert f"report-{run_id}.md" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_validation_errors(client):
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "", "analysis_date": "2025-06-01"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_with_llm_api_key(client):
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", return_value=None):
        resp = await client.post(
            "/api/v1/analysis",
            json={
                "ticker": "SPY",
                "analysis_date": "2025-06-01",
                "provider": "anthropic",
                "llm_api_key": "sk-minimax-test",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_llm_api_key_too_long_rejected(client):
    resp = await client.post(
        "/api/v1/analysis",
        json={
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "provider": "anthropic",
            "llm_api_key": "k" * 201,
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_snapshot_not_found(client):
    resp = await client.get("/api/v1/analysis/00000000-0000-0000-0000-000000000000/snapshot")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_not_found(client):
    resp = await client.post(
        "/api/v1/analysis/00000000-0000-0000-0000-000000000000/cancel",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_analysis_not_found(client):
    resp = await client.delete(
        "/api/v1/analysis/00000000-0000-0000-0000-000000000000",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_all_analyses(client):
    resp = await client.delete(
        "/api/v1/analysis",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert "deleted" in resp.json()


@pytest.mark.asyncio
async def test_backend_url_skips_key_check(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", return_value=None):
        with patch("backend.services.analysis_service.validate_backend_url", return_value="http://ollama:11434"):
            resp = await client.post(
                "/api/v1/analysis",
                json={
                    "ticker": "SPY", "analysis_date": "2025-06-01",
                    "backend_url": "http://ollama:11434",
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
    assert resp.status_code == 201
