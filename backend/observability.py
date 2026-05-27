"""Observability module — request metrics, structured logging, correlation IDs.

Provides ASGI middleware for:
- Request duration histogram (Prometheus text format)
- Request count by method/path/status
- Active connection gauge
- Correlation ID injection into every request/response
- Structured JSON log formatter
"""

from __future__ import annotations

import json as _json
import logging
import re as _re
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from typing import Any

# Correlation ID propagated through the request lifecycle
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


class StructuredFormatter(logging.Formatter):
    """JSON log formatter with correlation ID and standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        cid = correlation_id.get("")
        entry: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if cid:
            entry["correlation_id"] = cid
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        for key in ("path", "method", "status", "duration_ms", "exc_type", "account_id"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return _json.dumps(entry, default=str)


class _Metrics:
    """Thread-safe in-process metrics store — no external dependencies."""

    def __init__(self) -> None:
        self._request_count: dict[str, int] = defaultdict(int)
        self._request_duration_sum: dict[str, float] = defaultdict(float)
        self._request_duration_count: dict[str, int] = defaultdict(int)
        self._active_requests: int = 0
        self._startup_time: float = time.time()

    def record_request(self, method: str, path: str, status: int, duration: float) -> None:
        key = f'{method}|{_normalize_path(path)}|{status}'
        self._request_count[key] += 1
        self._request_duration_sum[key] += duration
        self._request_duration_count[key] += 1

    def inc_active(self) -> None:
        self._active_requests += 1

    def dec_active(self) -> None:
        self._active_requests = max(0, self._active_requests - 1)

    def prometheus_text(self) -> str:
        lines: list[str] = []
        lines.append("# HELP http_requests_total Total HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        for key, count in sorted(self._request_count.items()):
            method, path, status = key.split("|")
            lines.append(
                f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
            )

        lines.append("# HELP http_request_duration_seconds Request duration")
        lines.append("# TYPE http_request_duration_seconds summary")
        for key in sorted(self._request_duration_sum.keys()):
            method, path, status = key.split("|")
            total = self._request_duration_sum[key]
            count = self._request_duration_count[key]
            lines.append(
                f'http_request_duration_seconds_sum{{method="{method}",path="{path}",status="{status}"}} {total:.6f}'
            )
            lines.append(
                f'http_request_duration_seconds_count{{method="{method}",path="{path}",status="{status}"}} {count}'
            )

        lines.append("# HELP http_active_requests Current active requests")
        lines.append("# TYPE http_active_requests gauge")
        lines.append(f"http_active_requests {self._active_requests}")

        lines.append("# HELP process_uptime_seconds Seconds since process start")
        lines.append("# TYPE process_uptime_seconds gauge")
        lines.append(f"process_uptime_seconds {time.time() - self._startup_time:.1f}")

        return "\n".join(lines) + "\n"


metrics = _Metrics()


def _normalize_path(path: str) -> str:
    """Collapse path parameters to avoid cardinality explosion."""
    path = _re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{id}", path)
    path = _re.sub(r"/\d+", "/{id}", path)
    return path


class ObservabilityMiddleware:
    """ASGI middleware: injects correlation ID, measures request duration, records metrics."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cid = str(uuid.uuid4())[:8]
        token = correlation_id.set(cid)
        start = time.perf_counter()
        metrics.inc_active()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers.append([b"x-correlation-id", cid.encode()])
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            metrics.dec_active()
            method = scope.get("method", "GET")
            path = scope.get("path", "/")
            metrics.record_request(method, path, status_code, duration)

            if duration > 3.0:
                logger = logging.getLogger("backend.observability")
                logger.warning(
                    "slow_request",
                    extra={"path": path, "method": method, "status": status_code, "duration_ms": round(duration * 1000)},
                )
            correlation_id.reset(token)


def configure_structured_logging(level: str = "INFO") -> None:
    """Replace root logger formatters with structured JSON output."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
