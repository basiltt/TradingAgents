"""Two-phase mount + MCPManager — TASK-P0-03.

`register_mcp(app)` runs in create_app() body: installs a permanent indirection
mount at /mcp/rpc (initially the 503 gate) + the control-plane router. It reads
nothing and opens no DB connection.

`mcp_boot(app)` runs in lifespan AFTER migrations + scanner-resume: builds the
MCPManager, repairs the config singleton, and (if enabled) starts the transport.

The MCPManager owns the config repo, audit writer, and the live MCPServer; it is
the single object the control-plane router mutates. On any failure mcp_boot
degrades app.state.mcp_server to None and NEVER raises (NFR-007).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_GATE_BODY = b'{"detail":"feature disabled","code":"MCP_DISABLED"}'


def _make_resource_provider():
    from backend.mcp.resources.catalog import ResourceProvider

    return ResourceProvider()


def _make_prompt_provider():
    from backend.mcp.resources.catalog import PromptProvider

    return PromptProvider()


async def _gate_503(scope, receive, send) -> None:
    """ASGI app that returns 503 for http and acks lifespan; the default target
    of the /mcp/rpc indirection mount when MCP is disabled."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    if scope["type"] != "http":
        return
    await send({
        "type": "http.response.start",
        "status": 503,
        "headers": [[b"content-type", b"application/json"]],
    })
    await send({"type": "http.response.body", "body": _GATE_BODY})


class _Indirection:
    """Permanent ASGI mount target that forwards http/websocket to the current
    app.state.mcp_asgi, and self-acks lifespan (never forwards it downstream)."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        target = getattr(self._app.state, "mcp_asgi", None) or _gate_503
        await target(scope, receive, send)


class MCPManager:
    """Holds MCP runtime state and the enable/disable lifecycle."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self.config_repo = None
        self.audit_writer = None
        self.server = None  # the live MCPServer when enabled, else None

    async def boot(self) -> None:
        """Initialize repos, repair the singleton, and start the transport iff
        the persisted config is enabled. Degrades to disabled on any failure."""
        from backend.mcp.repositories.config_repo import MCPConfigRepository

        db = getattr(self._app.state, "db", None)
        pool = getattr(db, "pool", None) if db is not None else None
        if pool is None:
            logger.info("mcp_boot: no DB pool; MCP stays disabled")
            return
        self.config_repo = MCPConfigRepository(pool)
        await self.config_repo.repair_to_failsafe()
        cfg = await self.config_repo.get()
        if cfg.enabled:
            await self._start_transport(cfg)

    async def _start_transport(self, cfg) -> None:
        from backend.mcp.core.audit import AuditWriter
        from backend.mcp.core.registry import MCPConfigView
        from backend.mcp.core.server import MCPServer
        from backend.mcp.discovery import discover_tools
        from backend.mcp.repositories.audit_repo import AuditRepository

        discover_tools()  # populate the registry (composition layer, may import tools)
        db = self._app.state.db
        self.audit_writer = AuditWriter(AuditRepository(db.pool))
        await self.audit_writer.start()
        view = MCPConfigView(
            capability_tier=cfg.capability_tier,
            enabled_groups=cfg.enabled_groups,
            enabled_tools=cfg.enabled_tools,
        )
        self.server = MCPServer(
            config_view=view,
            app_state=self._app.state,
            audit_writer=self.audit_writer,
            available=self._service_available,
            resource_provider=_make_resource_provider(),
            prompt_provider=_make_prompt_provider(),
            debug_allowed=bool(cfg.safe_mode_flags.get("allow_debug", False)),
        )
        self._app.state.mcp_server = self.server

    def _service_available(self, group) -> bool:
        # P0: scans needs the db; everything else assumed available for now.
        from backend.mcp.core.registry import ToolGroup

        if group == ToolGroup.SCANS:
            return getattr(self._app.state, "db", None) is not None
        return True

    async def enable(self) -> None:
        cfg = await self.config_repo.get()
        await self.config_repo.update({"enabled": True}, expected_row_version=cfg.row_version)
        cfg = await self.config_repo.get()
        if self.server is None:
            await self._start_transport(cfg)

    async def disable(self, *, kill: bool = False) -> None:
        if kill:
            await self.config_repo.bump_kill_epoch()
        else:
            cfg = await self.config_repo.get()
            await self.config_repo.update({"enabled": False}, expected_row_version=cfg.row_version)
        await self._stop_transport()

    async def _stop_transport(self) -> None:
        self._app.state.mcp_server = None
        self._app.state.mcp_asgi = None
        if self.server is not None:
            await self.server.shutdown()
            self.server = None
        self.audit_writer = None

    async def shutdown(self) -> None:
        await self._stop_transport()


def register_mcp(app: Any) -> None:
    """create_app() body: permanent indirection mount + control-plane router.

    Reads nothing; opens no DB connection.
    """
    app.state.mcp_asgi = None
    app.state.mcp_server = None
    app.state.mcp_manager = None
    app.mount("/mcp/rpc", _Indirection(app))

    from backend.mcp.router import router as mcp_control_router

    app.include_router(mcp_control_router, prefix="/api/v1")


async def mcp_boot(app: Any) -> Optional[MCPManager]:
    """lifespan (after migrations + scanner-resume): build + boot the manager.

    Never raises; degrades app.state.mcp_server to None on any failure.
    """
    try:
        manager = MCPManager(app)
        app.state.mcp_manager = manager
        await manager.boot()
        return manager
    except Exception:  # noqa: BLE001
        logger.exception("mcp_boot_failed")
        app.state.mcp_server = None
        app.state.mcp_manager = None
        return None
