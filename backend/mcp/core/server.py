"""In-process MCP server bridge — TASK-P0-05.

`MCPServer` holds the resolved toolset and exposes `list_tools()` / `call_tool()`
that run through the dispatch pipeline + the single audit writer. The FastMCP
streamable-HTTP transport (mounted at /mcp/rpc) delegates to these methods; they
are also driven directly by the in-memory e2e test (no socket needed).
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from backend.mcp.core.audit import AuditWriter
from backend.mcp.core.clock import Clock, RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import (
    MCPConfigView,
    ToolSpec,
    discover_tools,
    resolve_enabled,
)
from backend.mcp.core.services import ServiceAccessors

# Protocol version negotiation bounds (streamable-HTTP).
PROTOCOL_FLOOR = "2025-03-26"
PROTOCOL_CEILING = "2025-06-18"
SERVER_NAME = "tradingagents-mcp"


def negotiate_protocol(requested: Optional[str]) -> str:
    """Return the protocol version to advertise. Down-negotiate, never error."""
    if requested and PROTOCOL_FLOOR <= requested <= PROTOCOL_CEILING:
        return requested
    return PROTOCOL_CEILING


class MCPServer:
    """The enabled toolset + dispatch + audit, resolved from config."""

    def __init__(
        self,
        *,
        config_view: MCPConfigView,
        app_state: Any,
        audit_writer: AuditWriter,
        available: Callable[[Any], bool] | None = None,
        clock: Clock | None = None,
        server_version: str = "0.1.0",
    ) -> None:
        self._config_view = config_view
        self._services = ServiceAccessors(app_state)
        self._audit = audit_writer
        self._available = available or (lambda group: True)
        self._clock = clock or RealClock()
        self._server_version = server_version
        discover_tools()
        self._enabled: dict[str, ToolSpec] = {
            s.name: s for s in resolve_enabled(config_view, available=self._available)
        }

    # --- MCP surface ---

    def initialize(self, *, requested_protocol: Optional[str] = None) -> dict[str, Any]:
        return {
            "serverInfo": {"name": SERVER_NAME, "version": self._server_version},
            "protocolVersion": negotiate_protocol(requested_protocol),
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
            },
            "instructions": (
                "Use optimize_config / sweep_run to find a better AutoTradeConfig. "
                "Read tools are side-effect-free. You can only PROPOSE config "
                "changes; a human approves them in the app UI."
            ),
        }

    def list_tools(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in self._enabled.values():
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "inputSchema": spec.input_schema.model_json_schema(),
                    "annotations": {
                        "readOnlyHint": not spec.mutating,
                        "destructiveHint": spec.mutating,
                        "idempotentHint": not spec.mutating,
                        "openWorldHint": spec.exchange_facing,
                    },
                }
            )
        return out

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, principal: str, session_id: str
    ) -> dict[str, Any]:
        spec = self._enabled.get(name)
        if spec is None:
            # disabled/unknown tool -> method-not-found semantics
            return {
                "isError": True,
                "code": -32601,
                "content": [{"type": "text", "text": f"[method_not_found] unknown tool {name!r}"}],
            }
        ctx = CallContext(
            principal=principal,
            session_id=session_id,
            tier=self._config_view.capability_tier,
            correlation_id=uuid.uuid4(),
            services=self._services,
            clock=self._clock,
        )
        return await dispatch(spec, arguments, ctx, audit=self._audit_enqueue)

    def _audit_enqueue(self, record: dict[str, Any]) -> None:
        # fire-and-forget onto the single writer's queue
        import asyncio

        asyncio.ensure_future(self._audit.enqueue(record))

    async def shutdown(self) -> None:
        await self._audit.shutdown()
