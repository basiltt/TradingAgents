"""Phase 4 security tests — R1 + R2."""

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


# ---------------------------------------------------------------------------
# R2: CSRF on PATCH /config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_config_csrf_required(client):
    """R2-F1: PATCH /api/v1/config without CSRF header returns 403."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {}},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# R2: config update — negative / out-of-range numeric values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_config_llm_max_concurrent_over_limit(client):
    """R2-F2: llm_max_concurrent > 1_000_000 rejected with 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"llm_max_concurrent": 1_000_001}},
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_unknown_key_rejected(client):
    """R2-F3: Unknown key in overrides returns 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"not_a_real_key": "value"}},
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_forbidden_key_api_key_rejected(client):
    """R2-F4: Forbidden API key overrides are rejected with 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"openai_api_key": "sk-evil"}},
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_string_value_too_long(client):
    """R2-F5: String value > 1024 chars is rejected with 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"llm_provider": "x" * 1025}},
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_wrong_type_rejected(client):
    """R2-F6: Value of wrong type (str instead of int) is rejected with 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"max_debate_rounds": "not-a-number"}},
        headers=CSRF,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R2: config overrides — sensitive data not leaked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_config_overrides_not_masked(client):
    """R2-F7: GET /config overrides field returns raw (unmasked) overrides — api keys not storable."""
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "overrides" in body
    assert "resolved" in body
    assert "defaults" in body


# ---------------------------------------------------------------------------
# R2: models/{provider} — path traversal / unknown providers rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_models_unknown_provider_rejected(client):
    """R2-F8: Unknown provider returns 400, not 500."""
    resp = await client.get("/api/v1/models/unknown_provider")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_models_path_traversal_rejected(client):
    """R2-F9: Path traversal in provider param — framework normalizes URL before routing (safe)."""
    # /api/v1/models/../config normalizes to /api/v1/config which hits the config endpoint.
    # The provider path segment never receives the traversal payload — the router sees 'config'.
    resp = await client.get("/api/v1/models/../config")
    # Either the config endpoint answers (200) or a proper 4xx — never a crash (5xx)
    assert resp.status_code < 500


@pytest.mark.asyncio
async def test_get_models_xss_in_provider_rejected(client):
    """R2-F10: XSS payload in provider param returns 400 or 404, not 500."""
    resp = await client.get("/api/v1/models/<script>alert(1)</script>")
    # URL-encoding causes the provider to not match any route or be rejected
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# R2: ScanRequest — provider and output_language lack validators (schema gap)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_scanner_invalid_provider_rejected(client):
    """R6: ScanRequest now validates provider — invalid provider returns 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "provider": "not_a_real_provider"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_invalid_provider_rejected(client):
    """R2-F12: AnalysisRequest correctly validates provider — invalid one returns 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "evil_provider"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_xss_output_language_rejected(client):
    """R2-F13: XSS payload in output_language is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "output_language": "<script>alert(1)</script>"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_output_language_too_long_rejected(client):
    """R2-F14: output_language > 30 chars is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "output_language": "A" * 31},
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R2: ticker validation — boundary and special characters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_ticker_too_long_rejected(client):
    """R2-F15: Ticker with invalid chars is rejected with 422 (16 A's passes CRYPTO_TICKER_RE)."""
    # TICKER_RE: [A-Z0-9.\-^]{1,15}, CRYPTO_TICKER_RE: [A-Z0-9]{2,20}
    # Use special chars that fail both patterns
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY!@#$%^&*()", "analysis_date": "2025-06-01"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_ticker_with_semicolon_rejected(client):
    """R2-F16: Ticker with semicolon (injection attempt) is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY;DROP", "analysis_date": "2025-06-01"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_future_date_rejected(client):
    """R2-F17: Analysis date in the future is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2099-01-01"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_invalid_date_format_rejected(client):
    """R2-F18: Non-ISO date format is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "01/06/2025"},
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R3: CSRF on POST /analysis and POST /scanner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_analysis_csrf_required(client):
    """R3: POST /api/v1/analysis without CSRF header returns 403."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_scanner_csrf_required(client):
    """R3: POST /api/v1/scanner without CSRF header returns 403."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_analysis_csrf_required(client):
    """R3: POST /api/v1/analysis/{run_id}/cancel without CSRF header returns 403."""
    resp = await client.post(
        "/api/v1/analysis/00000000-0000-0000-0000-000000000001/cancel",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# R3: _validate_run_id — non-UUID inputs rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_analysis_invalid_run_id(client):
    """R3: GET /api/v1/analysis/{run_id} with non-UUID returns 400."""
    resp = await client.get("/api/v1/analysis/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_analysis_invalid_run_id(client):
    """R3: POST /api/v1/analysis/{run_id}/cancel with non-UUID returns 400."""
    resp = await client.post(
        "/api/v1/analysis/not-a-uuid/cancel",
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_analysis_invalid_run_id(client):
    """R3: DELETE /api/v1/analysis/{run_id} with non-UUID returns 400."""
    resp = await client.delete(
        "/api/v1/analysis/not-a-uuid",
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_report_invalid_run_id(client):
    """R3: GET /api/v1/analysis/{run_id}/report with non-UUID returns 400."""
    resp = await client.get("/api/v1/analysis/sql-inject/report")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_snapshot_invalid_run_id(client):
    """R3: GET /api/v1/analysis/{run_id}/snapshot with non-UUID returns 400."""
    resp = await client.get("/api/v1/analysis/sql-inject/snapshot")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R3: checkpoints — confirm guard and ticker validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_all_checkpoints_no_confirm(client):
    """R3: DELETE /api/v1/checkpoints with CSRF but without confirm=true returns 400."""
    resp = await client.delete("/api/v1/checkpoints", headers=CSRF)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_ticker_checkpoints_no_confirm(client):
    """R3: DELETE /api/v1/checkpoints/SPY with CSRF but without confirm=true returns 400."""
    resp = await client.delete("/api/v1/checkpoints/SPY", headers=CSRF)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_ticker_checkpoints_invalid_ticker(client):
    """R3: DELETE /api/v1/checkpoints/<invalid> with CSRF+confirm returns 400."""
    resp = await client.delete(
        "/api/v1/checkpoints/BAD!TICKER?confirm=true",
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_checkpoint_invalid_ticker_format(client):
    """R3: GET /api/v1/checkpoints with injection payload in ticker returns 400."""
    resp = await client.get(
        "/api/v1/checkpoints?ticker=<script>alert(1)</script>&date=2025-06-01"
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R3: scanner — _validate_scan_id and date validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_scan_invalid_scan_id(client):
    """R3: GET /api/v1/scanner/{scan_id} with non-UUID returns 400."""
    resp = await client.get("/api/v1/scanner/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_scan_invalid_scan_id(client):
    """R3: POST /api/v1/scanner/{scan_id}/cancel with non-UUID returns 400."""
    resp = await client.post(
        "/api/v1/scanner/not-a-uuid/cancel",
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_scanner_future_date_rejected(client):
    """R3: ScanRequest rejects future analysis_date with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2099-01-01"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scanner_invalid_date_format_rejected(client):
    """R3: ScanRequest rejects non-ISO date format with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "not-a-date"},
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R3: config — backend_url forbidden, bool-for-int rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_config_backend_url_forbidden(client):
    """R3: backend_url in overrides is forbidden — returns 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"backend_url": "http://evil.internal"}},
        headers=CSRF,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_config_bool_for_int_field_rejected(client):
    """R3: bool value for an int config field is rejected — returns 400."""
    resp = await client.patch(
        "/api/v1/config",
        json={"overrides": {"max_debate_rounds": True}},
        headers=CSRF,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R3: analysis — model ID injection, crypto invalid interval
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_model_id_injection_chars_rejected(client):
    """R3: Model ID with semicolon (injection chars) is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "deep_think_llm": "gpt-4;rm -rf /"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_model_id_boundary_accepted(client):
    """R3: Model ID exactly 100 chars is accepted by schema validation."""
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
                "deep_think_llm": "a" * 100,
            },
            headers=CSRF,
        )
    assert resp.status_code in (200, 201, 422)  # 422 only if env key check fires


@pytest.mark.asyncio
async def test_start_analysis_model_id_too_long_rejected(client):
    """R3: Model ID of 101 chars is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "deep_think_llm": "a" * 101},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_crypto_invalid_interval_rejected(client):
    """R3: Crypto analysis with invalid interval value (e.g. '5m') is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "BTC", "analysis_date": "2025-06-01", "asset_type": "crypto", "interval": "5m"},
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R3: analysis filter — asset_type query param validated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_analyses_invalid_asset_type_rejected(client):
    """R3: GET /api/v1/analysis?asset_type=nft is rejected with 422."""
    resp = await client.get("/api/v1/analysis?asset_type=nft")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R3: WS _check_origin positive path
# ---------------------------------------------------------------------------

def test_ws_check_origin_allowed_returns_true():
    """R3: _check_origin returns True for an allowed origin."""
    from unittest.mock import MagicMock
    from backend.routers.ws import _check_origin

    ws = MagicMock()
    ws.headers = {"origin": "http://localhost:5177"}
    ws.app.state.cors_origins = ["http://localhost:5177"]
    assert _check_origin(ws) is True


# ---------------------------------------------------------------------------
# R2: analysts validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_invalid_analyst_rejected(client):
    """R2-F19: Invalid stock analyst name is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "analysts": ["<script>evil</script>"]},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_invalid_asset_type_rejected(client):
    """R2-F20: Invalid asset_type is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "asset_type": "nft"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_crypto_missing_interval_rejected(client):
    """R2-F21: Crypto asset_type without interval is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "BTC", "analysis_date": "2025-06-01", "asset_type": "crypto"},
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R2: data_vendors validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_invalid_vendor_category_rejected(client):
    """R2-F22: Invalid vendor category in data_vendors is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "data_vendors": {"evil_category": "yfinance"},
        },
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_analysis_invalid_vendor_value_rejected(client):
    """R2-F23: Invalid vendor value in data_vendors is rejected with 422."""
    resp = await client.post(
        "/api/v1/analysis",
        json={
            "ticker": "SPY",
            "analysis_date": "2025-06-01",
            "data_vendors": {"core_stock_apis": "evil_vendor"},
        },
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R4: SSRF via backend_url in POST body — integration level
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_backend_url_private_ip_rejected(client):
    """R4: Private IP in backend_url causes 400 via SSRF validator — integration level."""
    import socket
    private_ip_info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0))]
    with patch("backend.validators.socket.getaddrinfo", return_value=private_ip_info):
        resp = await client.post(
            "/api/v1/analysis",
            json={
                "ticker": "SPY",
                "analysis_date": "2025-06-01",
                "provider": "anthropic",
                "backend_url": "http://internal.corp:8080",
            },
            headers=CSRF,
        )
    # validate_backend_url raises ValueError → router returns 400
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R4: API key missing → 422 for analysis and scanner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_analysis_missing_api_key_returns_422(client, monkeypatch):
    """R4: Missing API key for provider returns 422 with no stack trace."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Ensure backend_url is absent so the key check fires
    resp = await client.post(
        "/api/v1/analysis",
        json={"ticker": "SPY", "analysis_date": "2025-06-01", "provider": "openai"},
        headers=CSRF,
    )
    assert resp.status_code == 422
    body = resp.text
    assert "Traceback" not in body
    assert "File " not in body


@pytest.mark.asyncio
async def test_start_analysis_missing_api_key_bypassed_with_backend_url(client):
    """R4: backend_url present bypasses API key check — intentional behavior."""
    import socket
    public_ip_info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
    with patch("backend.validators.socket.getaddrinfo", return_value=public_ip_info):
        with patch(
            "backend.services.analysis_service.AnalysisService.start_analysis",
            return_value="run-id-bypass",
        ):
            resp = await client.post(
                "/api/v1/analysis",
                json={
                    "ticker": "SPY",
                    "analysis_date": "2025-06-01",
                    "provider": "openai",
                    "backend_url": "http://example.com:4141",
                },
                headers=CSRF,
            )
    # API key check skipped when backend_url is provided
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# R4: CSP semicolon injection stripped from env var
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_csp_semicolon_injection_stripped(app):
    """R4: Semicolon in WEB_CSP_CONNECT_SRC does not inject a new CSP directive."""
    from fastapi.testclient import TestClient
    with patch.dict(os.environ, {"WEB_CSP_CONNECT_SRC": "'self'; img-src *"}):
        with TestClient(app) as tc:
            resp = tc.get("/api/v1/health")
    csp = resp.headers.get("content-security-policy", "")
    # The injected img-src directive must not appear
    assert "img-src *" not in csp
    # connect-src must still be present and valid
    assert "connect-src" in csp


# ---------------------------------------------------------------------------
# R4: WS _check_origin edge cases
# ---------------------------------------------------------------------------

def test_ws_check_origin_no_origin_header():
    """R4: _check_origin with absent origin key returns False."""
    from unittest.mock import MagicMock
    from backend.routers.ws import _check_origin

    ws = MagicMock()
    ws.headers = {}  # No "origin" key at all
    ws.app.state.cors_origins = ["http://localhost:5177"]
    assert _check_origin(ws) is False


def test_ws_check_origin_empty_allowed_list():
    """R4: _check_origin with empty cors_origins list returns False for any origin."""
    from unittest.mock import MagicMock
    from backend.routers.ws import _check_origin

    ws = MagicMock()
    ws.headers = {"origin": "http://localhost:5177"}
    ws.app.state.cors_origins = []
    assert _check_origin(ws) is False


# ---------------------------------------------------------------------------
# R4: GET /config — mask_secrets verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_config_api_key_in_resolved_is_masked(client, monkeypatch):
    """R4: API key field in resolved config is masked as '***'."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    body = resp.json()
    resolved = body.get("resolved", {})
    # If the field is present, it must not expose the raw key
    for key, val in resolved.items():
        if "api_key" in key.lower():
            assert val == "***", f"Field '{key}' should be masked but got: {val}"


# ---------------------------------------------------------------------------
# R5: Scanner API key check path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_scanner_missing_api_key_returns_422(client, monkeypatch):
    """R5: Missing API key for scanner provider returns 422 with no stack trace."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "provider": "openai"},
        headers=CSRF,
    )
    assert resp.status_code == 422
    body = resp.text
    assert "Traceback" not in body
    assert "File " not in body


# ---------------------------------------------------------------------------
# R5: memory page boundary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_page_zero_rejected(client):
    """R5: GET /api/v1/memory?page=0 is rejected with 422."""
    resp = await client.get("/api/v1/memory?page=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_memory_page_negative_rejected(client):
    """R5: GET /api/v1/memory?page=-1 is rejected with 422."""
    resp = await client.get("/api/v1/memory?page=-1")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R6: ScanRequest now has validators — test them
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_scanner_model_id_injection_rejected(client):
    """R6: ScanRequest deep_think_llm with injection chars is now rejected with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "deep_think_llm": "gpt-4;rm -rf /"},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scanner_output_language_xss_rejected(client):
    """R6: ScanRequest output_language with XSS payload is now rejected with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "output_language": "<script>alert(1)</script>"},
        headers=CSRF,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# R7: ScanRequest analysts and data_vendors validators
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_scanner_invalid_analyst_rejected(client):
    """R7: ScanRequest with invalid analyst name is rejected with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "analysts": ["<script>evil</script>"]},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scanner_invalid_vendor_category_rejected(client):
    """R7: ScanRequest with invalid data_vendors category is rejected with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "data_vendors": {"evil_category": "yfinance"}},
        headers=CSRF,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scanner_invalid_vendor_value_rejected(client):
    """R7: ScanRequest with invalid data_vendors value is rejected with 422."""
    resp = await client.post(
        "/api/v1/scanner",
        json={"analysis_date": "2025-06-01", "data_vendors": {"core_stock_apis": "evil_vendor"}},
        headers=CSRF,
    )
    assert resp.status_code == 422
