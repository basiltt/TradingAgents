"""FastMCP streamable-HTTP transport adapter — TASK-P0-05 (transport wiring).

Builds a FastMCP instance whose tools delegate to our `MCPServer` (so the full
dispatch pipeline — tier-gate, audit, redaction — runs for every call), and wraps
its streamable-HTTP ASGI app with bearer-auth + Host/Origin middleware. This is
what `app.state.mcp_asgi` points at when the feature is enabled.

The session-manager lifecycle is started/stopped explicitly by the caller (mount)
since the app is swapped behind a permanent indirection mount, not mounted via
Starlette's normal lifespan.
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Annotated, Any, Optional

from backend.mcp.core.auth import BearerAuthenticator
from backend.mcp.core.netguard import host_origin_allowed

logger = logging.getLogger(__name__)


def build_fastmcp_app(server: Any, *, token_hash: Optional[str]) -> tuple[Any, Any]:
    """Build the FastMCP streamable-HTTP ASGI app + its session manager.

    `server` is our MCPServer. Each enabled tool is registered as a FastMCP tool
    that delegates to `server.call_tool`, so our pipeline runs. Returns
    (asgi_app, session_manager) — the caller starts the manager's task group.
    """
    from mcp.server.fastmcp import FastMCP

    fast = FastMCP(
        "tradingagents-mcp",
        stateless_http=True,  # no server-side session store needed for our model
        json_response=True,
    )

    # Register each enabled tool as a thin delegate to MCPServer.call_tool.
    for spec in server.enabled_specs():
        _register_delegate(fast, server, spec)

    asgi = fast.streamable_http_app()
    guarded = _AuthHostGuard(asgi, BearerAuthenticator(token_hash))
    return guarded, getattr(fast, "session_manager", None)


def _register_delegate(fast: Any, server: Any, spec: Any) -> None:
    input_model = spec.input_schema

    async def _delegate(**kwargs: Any) -> dict[str, Any]:
        # principal/session are bound at the guard layer; use a stable id here.
        # kwargs is already the flat field map (the synthesized signature below
        # makes FastMCP pass each real field as a keyword); dispatch re-validates
        # it via spec.input_schema(**raw_args).
        result = await server.call_tool(
            spec.name, kwargs, principal=server.principal_hint(), session_id="http"
        )
        return result

    # FastMCP derives the advertised inputSchema by introspecting this delegate's
    # signature. A bare `**kwargs` would collapse to a single `kwargs` property,
    # making every parameterized tool uncallable over HTTP. Synthesize a real
    # signature from the tool's Pydantic input model so the wire schema mirrors
    # spec.input_schema (field names, required set, and per-field constraints).
    # We keep `**kwargs` as the actual runtime container — the synthesized
    # KEYWORD_ONLY params are introspection-only — so the body still forwards a
    # flat dict unchanged.
    _delegate.__name__ = spec.name
    # functions honor a custom __signature__ at runtime (read by inspect.signature),
    # but typeshed doesn't declare the attribute as settable on a function object.
    _sig = _model_signature(input_model)
    _delegate.__signature__ = _sig  # type: ignore[attr-defined]  # runtime-supported on functions
    _delegate.__annotations__ = {
        name: param.annotation
        for name, param in _sig.parameters.items()
    }
    _delegate.__annotations__["return"] = dict
    fast.add_tool(
        _delegate,
        name=spec.name,
        description=spec.description,
        # Our dispatch pipeline already returns a complete MCP result envelope
        # (isError / structuredContent / content). structured_output=False tells
        # FastMCP to pass that envelope through instead of re-wrapping the return
        # value as structured output (which would also demand a model return
        # annotation the delegate doesn't have).
        structured_output=False,
    )


def _model_signature(model: Any) -> "inspect.Signature":
    """Build an inspect.Signature whose KEYWORD_ONLY parameters mirror `model`'s
    Pydantic fields (annotation + required/default), carrying each FieldInfo via
    Annotated so FastMCP advertises the field's constraints/description."""
    params: list[inspect.Parameter] = []
    for field_name, field_info in model.model_fields.items():
        # Dynamic Annotated build: field_info.annotation is a runtime value, but mypy
        # parses Annotated[]'s first arg as a static type-form. Valid at runtime.
        annotated = Annotated[field_info.annotation, field_info]  # type: ignore[name-defined]  # runtime type-form
        default = (
            inspect.Parameter.empty
            if field_info.is_required()
            else field_info.default
        )
        params.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotated,
                default=default,
            )
        )
    return inspect.Signature(params, return_annotation=dict)


class _AuthHostGuard:
    """ASGI middleware: Host/Origin allowlist + bearer auth before the transport."""

    def __init__(self, app: Any, authenticator: BearerAuthenticator) -> None:
        self._app = app
        self._auth = authenticator

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            # the manager lifecycle is driven explicitly by the mount; ack here.
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] != "http":
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        host = headers.get("host")
        origin = headers.get("origin")
        if not host_origin_allowed(host=host, origin=origin):
            await _reject(send, 403, "host/origin not allowed")
            return
        if self._auth.authenticate(headers) is None:
            await _reject(send, 401, "missing or invalid bearer token")
            return
        await self._app(scope, receive, send)


async def _reject(send, status: int, message: str) -> None:
    body = json.dumps({"detail": message}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [[b"content-type", b"application/json"]],
    })
    await send({"type": "http.response.body", "body": body})
