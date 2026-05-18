"""Unit tests for observability module — metrics, middleware, structured logging."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from backend.observability import (
    ObservabilityMiddleware,
    StructuredFormatter,
    _Metrics,
    _normalize_path,
    configure_structured_logging,
    correlation_id,
    metrics,
)


class TestNormalizePath:
    def test_collapses_uuid(self):
        path = "/api/v1/accounts/550e8400-e29b-41d4-a716-446655440000/trades"
        assert _normalize_path(path) == "/api/v1/accounts/{id}/trades"

    def test_collapses_numeric_id(self):
        assert _normalize_path("/api/v1/scans/12345") == "/api/v1/scans/{id}"

    def test_leaves_normal_path(self):
        assert _normalize_path("/api/v1/health") == "/api/v1/health"


class TestMetrics:
    def test_record_and_export(self):
        m = _Metrics()
        m.record_request("GET", "/api/v1/health", 200, 0.05)
        m.record_request("POST", "/api/v1/trades", 201, 0.12)
        text = m.prometheus_text()
        assert "http_requests_total" in text
        assert 'method="GET"' in text
        assert "http_active_requests 0" in text
        assert "process_uptime_seconds" in text

    def test_active_requests(self):
        m = _Metrics()
        m.inc_active()
        m.inc_active()
        assert m._active_requests == 2
        m.dec_active()
        assert m._active_requests == 1
        m.dec_active()
        m.dec_active()
        assert m._active_requests == 0


class TestStructuredFormatter:
    def test_formats_json(self):
        import json
        formatter = StructuredFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello world", (), None)
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["msg"] == "hello world"
        assert parsed["level"] == "INFO"

    def test_includes_correlation_id(self):
        import json
        token = correlation_id.set("abc123")
        try:
            formatter = StructuredFormatter()
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["correlation_id"] == "abc123"
        finally:
            correlation_id.reset(token)

    def test_includes_extra_fields(self):
        import json
        formatter = StructuredFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.path = "/api/test"  # type: ignore[attr-defined]
        record.duration_ms = 42  # type: ignore[attr-defined]
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["path"] == "/api/test"
        assert parsed["duration_ms"] == 42


class TestMiddleware:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_injects_correlation_id_header(self):
        headers_captured = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = ObservabilityMiddleware(app)

        async def mock_send(msg):
            if msg["type"] == "http.response.start":
                headers_captured.extend(msg.get("headers", []))

        scope = {"type": "http", "method": "GET", "path": "/test"}
        await middleware(scope, AsyncMock(), mock_send)

        header_names = [h[0] for h in headers_captured]
        assert b"x-correlation-id" in header_names

    @pytest.mark.asyncio(loop_scope="function")
    async def test_passthrough_non_http(self):
        called = []

        async def app(scope, receive, send):
            called.append(True)

        middleware = ObservabilityMiddleware(app)
        await middleware({"type": "websocket"}, AsyncMock(), AsyncMock())
        assert called
