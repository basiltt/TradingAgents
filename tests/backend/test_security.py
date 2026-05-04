"""Phase 4 security tests — R1."""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch


@pytest.fixture
def app(tmp_path):
    os.environ["TRADINGAGENTS_WEB_DB_PATH"] = str(tmp_path / "test.db")
    from backend.main import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c


CSRF = {"X-Requested-With": "XMLHttpRequest"}


# ---------------------------------------------------------------------------
# CSRF enforcement — DELETE paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_analysis_csrf_required(client):
    """R1-F3: DELETE /api/v1/analysis/<id> requires CSRF header."""
    resp = await client.delete("/api/v1/analysis/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_all_analyses_csrf_required(client):
    """R1-F3: DELETE /api/v1/analysis requires CSRF header."""
    resp = await client.delete("/api/v1/analysis")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_ticker_checkpoints_csrf_required(client):
    """R1-F4: DELETE /api/v1/checkpoints/{ticker} requires CSRF header."""
    resp = await client.delete("/api/v1/checkpoints/SPY?confirm=true")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_all_checkpoints_csrf_required(client):
    """R1-F4: DELETE /api/v1/checkpoints requires CSRF header."""
    resp = await client.delete("/api/v1/checkpoints?confirm=true")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_scan_csrf_required(client):
    """R1-F4: POST /api/v1/scanner/{id}/cancel requires CSRF header."""
    resp = await client.post("/api/v1/scanner/00000000-0000-0000-0000-000000000001/cancel")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# SQL injection in query params — parameterized queries must stay safe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_analyses_ticker_sql_injection(client):
    """R1-F2: ticker filter with SQL injection payload returns safe empty result."""
    resp = await client.get("/api/v1/analysis?ticker='; DROP TABLE analysis_runs; --")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_analyses_status_sql_injection(client):
    """R1-F2: status filter with SQL injection payload returns safe empty result."""
    resp = await client.get("/api/v1/analysis?status='; DROP TABLE--")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_analyses_from_date_injection(client):
    """R1-F3: from_date with injection payload returns safe empty result."""
    resp = await client.get("/api/v1/analysis?from_date=2020-01-01' OR '1'='1")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_analyses_to_date_invalid(client):
    """R1-F3: to_date with non-date value returns graceful result."""
    resp = await client.get("/api/v1/analysis?from_date=not-a-date&to_date=99999999")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_analyses_ticker_xss(client):
    """R1-F2: XSS payload in ticker filter is treated as literal string — no 500."""
    resp = await client.get("/api/v1/analysis?ticker=<script>alert(1)</script>")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# Missing required fields (schema validation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_missing_ticker(client):
    """R1-F8: POST /api/v1/analysis without ticker returns 422."""
    with patch("backend.services.analysis_service.AnalysisService.start_analysis"):
        resp = await client.post(
            "/api/v1/analysis",
            json={"analysis_date": "2025-06-01"},
            headers=CSRF,
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_missing_date(client):
    """R1-F8: POST /api/v1/analysis without analysis_date returns 422."""
    with patch("backend.services.analysis_service.AnalysisService.start_analysis"):
        resp = await client.post(
            "/api/v1/analysis",
            json={"ticker": "SPY"},
            headers=CSRF,
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_empty_body(client):
    """R1-F8: POST /api/v1/analysis with empty body returns 422."""
    resp = await client.post("/api/v1/analysis", json={}, headers=CSRF)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scanner_missing_date(client):
    """R1-F9: POST /api/v1/scanner without analysis_date returns 422."""
    resp = await client.post("/api/v1/scanner", json={}, headers=CSRF)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_checkpoint_missing_date(client):
    """R1-F10: GET /api/v1/checkpoints without date returns 422."""
    resp = await client.get("/api/v1/checkpoints?ticker=SPY")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_checkpoint_missing_ticker(client):
    """R1-F10: GET /api/v1/checkpoints without ticker returns 422."""
    resp = await client.get("/api/v1/checkpoints?date=2025-06-01")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Malformed JSON body
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_analysis_malformed_json(client):
    """R1-F5: POST /api/v1/analysis with malformed JSON body returns 422."""
    resp = await client.post(
        "/api/v1/analysis",
        content=b"{bad json",
        headers={**CSRF, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_scanner_malformed_json(client):
    """R1-F6: POST /api/v1/scanner with malformed JSON body returns 422."""
    resp = await client.post(
        "/api/v1/scanner",
        content=b"not json at all",
        headers={**CSRF, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_config_malformed_json(client):
    """R1-F7: PATCH /api/v1/config with malformed JSON returns 422."""
    resp = await client.patch(
        "/api/v1/config",
        content=b'{"overrides": ',
        headers={**CSRF, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Schema boundary validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_research_depth_too_low(client):
    """R1-F13: research_depth=0 is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "research_depth": 0},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_research_depth_too_high(client):
    """R1-F13: research_depth=6 is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "research_depth": 6},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_analyses_limit_boundary_at_max(client):
    """R1-F16: limit=10000 is accepted, limit=10001 is rejected."""
    resp_ok = await client.get("/api/v1/analysis?limit=10000")
    assert resp_ok.status_code == 200
    resp_bad = await client.get("/api/v1/analysis?limit=10001")
    assert resp_bad.status_code == 422


@pytest.mark.asyncio
async def test_list_analyses_limit_zero_rejected(client):
    """R1-F16: limit=0 is rejected with 422."""
    resp = await client.get("/api/v1/analysis?limit=0")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CSP header value and injection prevention
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_csp_header_contains_frame_ancestors(client):
    """R1-F5: CSP header includes frame-ancestors 'none'."""
    resp = await client.get("/api/v1/health")
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp


@pytest.mark.asyncio
async def test_csp_header_injection_via_env_var(app):
    """R1-F8: Newline injection in WEB_CSP_CONNECT_SRC is sanitized."""
    from fastapi.testclient import TestClient
    with patch.dict(os.environ, {"WEB_CSP_CONNECT_SRC": "'self'\r\nX-Injected: evil"}):
        with TestClient(app) as tc:
            resp = tc.get("/api/v1/health")
    csp = resp.headers.get("content-security-policy", "")
    assert "\n" not in csp
    assert "X-Injected" not in csp


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cors_allowed_origin_reflected(client):
    """R1-F10: Allowed origin gets ACAO header in actual request."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:5177"},
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao == "http://localhost:5177"


@pytest.mark.asyncio
async def test_cors_disallowed_origin_not_reflected(client):
    """R1-F10: Disallowed origin does not get ACAO header."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Origin": "http://evil.com"},
    )
    assert resp.headers.get("access-control-allow-origin") is None


# ---------------------------------------------------------------------------
# WebSocket origin edge cases
# ---------------------------------------------------------------------------

def test_ws_check_origin_empty_string():
    """R1-F7: Empty Origin header is treated as absent (returns False)."""
    from unittest.mock import MagicMock
    from backend.routers.ws import _check_origin

    ws = MagicMock()
    ws.headers = {"origin": ""}
    ws.app.state.cors_origins = ["http://localhost:5177"]
    assert _check_origin(ws) is False


def test_ws_check_origin_case_sensitive():
    """R1-F8: Origin check is case-sensitive — uppercase scheme is rejected."""
    from unittest.mock import MagicMock
    from backend.routers.ws import _check_origin

    ws = MagicMock()
    ws.headers = {"origin": "HTTP://localhost:5177"}
    ws.app.state.cors_origins = ["http://localhost:5177"]
    assert _check_origin(ws) is False


# ---------------------------------------------------------------------------
# Validators — URL scheme coverage
# ---------------------------------------------------------------------------

def test_validate_url_javascript_scheme_blocked():
    """R1-F20: javascript: scheme is blocked."""
    from backend.validators import validate_backend_url
    with pytest.raises(ValueError):
        validate_backend_url("javascript:alert(1)", server_port=8000)


def test_validate_url_data_scheme_blocked():
    """R1-F20: data: scheme is blocked."""
    from backend.validators import validate_backend_url
    with pytest.raises(ValueError):
        validate_backend_url("data:text/html,evil", server_port=8000)


def test_validate_url_file_scheme_blocked():
    """R1-F20: file: scheme is blocked."""
    from backend.validators import validate_backend_url
    with pytest.raises(ValueError):
        validate_backend_url("file:///etc/passwd", server_port=8000)


# ---------------------------------------------------------------------------
# Extra field in request body is silently stripped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_extra_fields_stripped(client):
    """R1-F18: Extra unknown fields in POST body are silently ignored (not leaked)."""
    with patch(
        "backend.services.analysis_service.AnalysisService.start_analysis",
        return_value="run-id-123",
    ):
        resp = await client.post(
            "/api/v1/analysis",
            json={
                "ticker": "SPY",
                "analysis_date": "2025-06-01",
                "provider": "anthropic",
                "evil_field": "<script>alert(1)</script>",
            },
            headers=CSRF,
        )
    assert resp.status_code in (200, 201, 202)
    body = resp.text
    assert "evil_field" not in body
    assert "<script>" not in body


# ---------------------------------------------------------------------------
# HTTP Method Not Allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_health_method_not_allowed(client):
    """R1-F19: POST /api/v1/health returns 405."""
    resp = await client.post("/api/v1/health", headers=CSRF)
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_delete_memory_method_not_allowed(client):
    """R1-F19: DELETE /api/v1/memory returns 405."""
    resp = await client.delete("/api/v1/memory", headers=CSRF)
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_memory_limit_upper_boundary(client):
    """R1-F17: memory limit=200 accepted, limit=201 rejected."""
    resp_ok = await client.get("/api/v1/memory?limit=200")
    assert resp_ok.status_code == 200
    resp_bad = await client.get("/api/v1/memory?limit=201")
    assert resp_bad.status_code == 422
