"""Dispatch pipeline — TASK-P0-06.

The single place cross-cutting concerns are applied around every tool handler:
tier-gate -> audit-begin -> arg-validate -> timeout(handler) -> audit-end ->
error-map -> shape. Handlers receive validated args + a CallContext and return a
Pydantic model (or raise a domain error). They never touch app.state directly.

Auth + host/origin happen at the transport edge (TASK-P0-09/07); this function
is the per-call core and is unit-testable with no transport.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel, ValidationError

from backend.mcp.core.clock import Clock
from backend.mcp.core.errors import (
    MCPDeniedError,
    MCPValidationError,
    map_exception,
)
from backend.mcp.core.registry import ToolSpec, tier_allows

_DEFAULT_TIMEOUT_S = 120.0


@dataclass
class CallContext:
    principal: str
    session_id: str
    tier: str
    correlation_id: Optional[str]
    services: Any
    clock: Clock


def _ok_result(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump()
    return {
        "isError": False,
        "structuredContent": data,
        "content": [{"type": "text", "text": _summary_text(data)}],
    }


def _error_result(code: str, message: str) -> dict[str, Any]:
    return {
        "isError": True,
        "content": [{"type": "text", "text": f"[{code}] {message}"}],
    }


def _summary_text(data: dict[str, Any]) -> str:
    keys = ", ".join(list(data.keys())[:8])
    return f"ok ({keys})" if keys else "ok"


async def dispatch(
    spec: ToolSpec,
    raw_args: dict[str, Any],
    ctx: CallContext,
    *,
    audit: Callable[[dict[str, Any]], Any],
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run one tool call through the cross-cutting pipeline. Always returns a
    tool result dict (never raises)."""
    started = ctx.clock.now()
    record: dict[str, Any] = {
        "tool_name": spec.name,
        "tool_group": spec.group.value,
        "safety_class": spec.safety_class.value,
        "mutating": spec.mutating,
        "principal_token_id": ctx.principal,
        "session_id": ctx.session_id,
        "correlation_id": str(ctx.correlation_id) if ctx.correlation_id else None,
        "status": "ok",
        "error": None,
    }

    def _finalize(result: dict[str, Any], status: str, error: Optional[str]) -> dict[str, Any]:
        record["status"] = status
        record["error"] = error
        try:
            record["duration_ms"] = int(
                (ctx.clock.now() - started).total_seconds() * 1000
            )
        except Exception:
            record["duration_ms"] = None
        audit(record)
        return result

    try:
        # tier-gate
        if not tier_allows(spec.safety_class, ctx.tier):
            raise MCPDeniedError(
                f"tool {spec.name!r} denied at tier {ctx.tier} "
                f"(requires {spec.safety_class.value})"
            )
        # arg validation
        try:
            args = spec.input_schema(**raw_args)
        except ValidationError as ve:
            raise MCPValidationError(str(ve.errors()[:1])) from ve
        # handler under timeout
        result_model = await asyncio.wait_for(spec.handler(args, ctx), timeout=timeout_s)
        return _finalize(_ok_result(result_model), "ok", None)
    except asyncio.TimeoutError:
        return _finalize(_error_result("timeout", "tool timed out"), "timeout", "timeout")
    except BaseException as exc:  # noqa: BLE001 — catch-all boundary (R-265)
        mapped = map_exception(exc)
        return _finalize(_error_result(mapped.code, mapped.message), mapped.status, mapped.code)
