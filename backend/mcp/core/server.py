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
        resource_provider: Any | None = None,
        prompt_provider: Any | None = None,
        debug_allowed: bool = False,
    ) -> None:
        self._config_view = config_view
        self._services = ServiceAccessors(app_state)
        self._audit = audit_writer
        self._available = available or (lambda group: True)
        self._clock = clock or RealClock()
        self._server_version = server_version
        self._resources = resource_provider
        self._prompts = prompt_provider
        self._enabled: dict[str, ToolSpec] = {
            s.name: s
            for s in resolve_enabled(
                config_view, available=self._available, debug_allowed=debug_allowed
            )
        }

    # --- MCP surface ---

    def initialize(self, *, requested_protocol: Optional[str] = None) -> dict[str, Any]:
        """Build the MCP `initialize` response (server info, negotiated protocol, capabilities)."""
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

    def enabled_specs(self) -> list[ToolSpec]:
        """The enabled ToolSpecs (for transport registration)."""
        return list(self._enabled.values())

    def self_test(self) -> bool:
        """Dry-connect self-test (FR-003): prove the server is functional by
        negotiating the protocol and enumerating tools without raising. Returns
        True on success; the enable flow rolls back if this fails."""
        try:
            info = self.initialize()
            assert info.get("protocolVersion")
            _ = self.list_tools()  # advertised set must build cleanly
            return True
        except Exception:  # noqa: BLE001 — any failure means do-not-enable
            return False

    def principal_hint(self) -> str:
        """A stable non-secret principal id for HTTP-delegated calls (the bearer
        is validated at the transport guard; this only labels the audit record)."""
        return "http-agent"

    def list_tools(self) -> list[dict[str, Any]]:
        """List enabled tools as MCP descriptors (name, description, input schema, hint annotations)."""
        return [
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
            for spec in self._enabled.values()
        ]

    # --- resources / prompts (P1) — providers injected at composition time ---

    def list_resources(self) -> list[dict[str, str]]:
        """List static MCP resources from the provider, or [] if none configured."""
        if self._resources is None:
            return []
        return list(self._resources.resources)

    def list_resource_templates(self) -> list[dict[str, str]]:
        """resources/templates/list — parameterized resource URIs (e.g. scan/{id})."""
        if self._resources is None:
            return []
        getter = getattr(self._resources, "templates", None)
        return list(getter) if getter else []

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI via the provider; raises ValueError if resources are unavailable."""
        if self._resources is None:
            raise ValueError("resources not available")
        return await self._resources.read(uri, self._services, self._server_version)

    def list_prompts(self) -> list[dict[str, Any]]:
        """List available MCP prompts from the provider, or [] if none configured."""
        if self._prompts is None:
            return []
        return self._prompts.list()

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render a named prompt with the given arguments; raises ValueError if prompts are unavailable."""
        if self._prompts is None:
            raise ValueError("prompts not available")
        return self._prompts.get(name, arguments)

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, principal: str, session_id: str
    ) -> dict[str, Any]:
        """Dispatch a tool call through validation + audit; returns its result envelope.

        Returns a method-not-found error envelope (code -32601) if the tool is
        unknown or disabled.
        """
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
            correlation_id=str(uuid.uuid4()),
            services=self._services,
            clock=self._clock,
        )
        return await dispatch(spec, arguments, ctx, audit=self._audit.enqueue)

    async def shutdown(self) -> None:
        """Flush and stop the background audit writer."""
        await self._audit.shutdown()
