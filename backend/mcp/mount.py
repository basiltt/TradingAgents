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

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The single ASGI mount path for the MCP transport. Exported so the control-plane
# router can advertise the exact same path it is mounted at — if this ever moves,
# the operator-facing endpoint URL moves with it (no silent drift).
MCP_RPC_PATH = "/mcp/rpc"

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
        self._transport_cm = None
        self.last_error: Optional[str] = None  # last transport-start failure (for status)
        # Live-trading protection (RK-1): wired at _start_transport, enforced by
        # the sweep tools via the manager handle on app.state.mcp_manager.
        self.leader = None        # MCPLeader — held while this worker is the MCP leader
        self.db_floor = None      # DbFloor — caps MCP/sweep DB acquisitions
        self.breaker = None       # LiveSLIBreaker — suspends sweep work on SLI degradation
        self._sli_task = None     # background SLI poll feeding the breaker

    def mcp_permitted(self) -> bool:
        """Runtime gate the sweep tools check before admitting CPU/DB work — the
        breaker trips this to False when live-trading SLIs degrade (fail-closed
        when the breaker is absent)."""
        return self.breaker is None or self.breaker.mcp_permitted()

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

    async def _acquire_leadership(self) -> bool:
        """Become the MCP leader (FR-034). Single-worker → always leader; with
        WEB_CONCURRENCY>1 only one worker wins the advisory lock, the rest stay
        OFF (the hash-chained single-writer audit assumes one server)."""
        import os

        from backend.mcp.leader import MCPLeader

        if self.leader is not None and self.leader.is_leader:
            return True
        # Single-worker is the supported topology; the lock is a multi-worker guard.
        concurrency = int(os.environ.get("WEB_CONCURRENCY", "1") or "1")
        if concurrency <= 1:
            return True
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            return True  # can't contend without a dsn; single-worker assumption holds
        self.leader = MCPLeader()
        got = await self.leader.acquire(dsn)
        if not got:
            logger.info("mcp: not the leader (another worker holds the lock); staying OFF")
        return got

    async def _poll_slis(self) -> None:
        """Feed the live-SLI breaker on a cadence. Always measures event-loop lag
        in-process (a real, dependency-free signal: if the loop is starved, order
        placement is too), and merges any richer SLIs the app exposes via
        app.state.mcp_live_slis (callable or dict of {metric: value}). The breaker
        trips OPEN when any bounded metric exceeds its bound, suspending sweeps.
        Runs until cancelled."""
        bounds = {
            "loop_lag_ms": 250.0,
            "order_p95_ms": 500.0,
            "reconciler_cycle_ms": 2000.0,
            "pool_wait_ms": 500.0,
        }
        interval = 2.0
        while True:
            try:
                # 1. measure event-loop lag: schedule a wake-up `interval` out and
                #    see how late it actually fires. Late wake = a busy/starved loop.
                t0 = asyncio.get_running_loop().time()
                await asyncio.sleep(interval)
                lag_ms = max(0.0, (asyncio.get_running_loop().time() - t0 - interval) * 1000.0)
                sample: dict[str, float] = {"loop_lag_ms": lag_ms}

                # 2. merge any app-provided SLIs (defensive: only finite numbers).
                src = getattr(self._app.state, "mcp_live_slis", None)
                extra = src() if callable(src) else src
                if isinstance(extra, dict):
                    for k, v in extra.items():
                        try:
                            fv = float(v)
                            if fv == fv and fv not in (float("inf"), float("-inf")):
                                sample[k] = fv
                        except (TypeError, ValueError):
                            # unparsable metric → treat as a breach (fail-closed)
                            sample[k] = bounds.get(k, 0.0) + 1.0

                if self.breaker is not None:
                    self.breaker.observe_metrics(sample, bounds=bounds)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — never let SLI polling crash the manager
                logger.exception("mcp_sli_poll_error")
                await asyncio.sleep(interval)

    async def _start_transport(self, cfg) -> None:
        from backend.mcp.core.audit import AuditWriter
        from backend.mcp.core.registry import MCPConfigView
        from backend.mcp.core.server import MCPServer
        from backend.mcp.discovery import discover_tools
        from backend.mcp.repositories.audit_repo import AuditRepository

        discover_tools()  # populate the registry (composition layer, may import tools)
        db = self._app.state.db

        # Leader election (FR-034): refuse to start a SECOND MCP server in a
        # multi-worker deployment — the single-writer audit chain requires one.
        if not await self._acquire_leadership():
            self.last_error = "not_mcp_leader"
            # acquire() already closed its connection on a lost contention; null
            # the handle so a later re-enable contends cleanly (no stale object).
            self.leader = None
            return

        # Live-trading protection (FR-035/037): a reserved DB-pool floor caps
        # MCP/sweep acquisitions, and a live-SLI breaker suspends sweep work when
        # the trading loop degrades. Both are read by the sweep tools via
        # app.state.mcp_manager. Built here so they exist for the whole ON window.
        try:
            from backend.mcp.core.breaker import LiveSLIBreaker
            from backend.mcp.core.dbfloor import DbFloor

            pool_max = getattr(db.pool, "_maxsize", 0) or getattr(db.pool, "maxsize", 0) or 10
            live_floor = max(2, int(pool_max * 0.4))
            self.db_floor = DbFloor(pool_max=pool_max, live_floor=live_floor)
            self.breaker = LiveSLIBreaker(trip_threshold=3, reset_threshold=5)
            self._app.state.mcp_db_floor = self.db_floor
            self._sli_task = asyncio.create_task(self._poll_slis())
        except Exception:  # noqa: BLE001 — protection build is best-effort; log + continue
            logger.exception("mcp_protection_build_failed")

        # Wire the SweepRepository so ctx.services.sweep_repo resolves for the
        # async sweep tools, and run boot crash-recovery (mark orphaned 'running'
        # sweeps 'interrupted' so they're never perpetually running — AC-023).
        try:
            from backend.mcp.repositories.sweep_repo import SweepRepository

            sweep_repo = SweepRepository(db.pool)
            self._app.state.mcp_sweep_repo = sweep_repo
            n = await sweep_repo.recover_interrupted()
            if n:
                logger.info("mcp_sweep_recovery: marked %d interrupted", n)
        except Exception:  # noqa: BLE001 — recovery is best-effort
            logger.exception("mcp_sweep_recovery_failed")
        # Build audit writer + server + transport under ONE guard so a partial
        # failure can't leave the audit task running orphaned or the server set
        # while the transport is dead. On any failure: tear down what started,
        # record the error for the status surface, and degrade to disabled.
        try:
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

            from backend.mcp.core.transport import build_fastmcp_app

            asgi, manager = build_fastmcp_app(self.server, token_hash=cfg.access_token_hash)
            if manager is not None:
                self._transport_cm = manager.run()
                await self._transport_cm.__aenter__()
            self._app.state.mcp_asgi = asgi
            self.last_error = None
        except Exception as exc:  # noqa: BLE001 — degrade to disabled, never crash the host
            logger.exception("mcp_transport_start_failed")
            self.last_error = repr(exc)
            # best-effort teardown of whatever started
            await self._stop_transport()
            self._app.state.mcp_asgi = None
            self._app.state.mcp_server = None
            self.server = None

    def _service_available(self, group) -> bool:
        """Per-group backing-service presence (R-availability). A tool is only
        advertised when the service it calls actually exists, so the agent +
        the UI budget never see a tool that would fail at call time."""
        from backend.mcp.core.registry import ToolGroup

        st = self._app.state
        has = lambda name: getattr(st, name, None) is not None  # noqa: E731
        if group in (ToolGroup.SCANS, ToolGroup.SCHEDULED, ToolGroup.STRATEGIES, ToolGroup.PORTFOLIO):
            return has("db")
        if group in (ToolGroup.ACCOUNTS, ToolGroup.POSITIONS, ToolGroup.ANALYTICS):
            return has("accounts_service")
        if group is ToolGroup.TRADES:
            return has("trade_repo") and has("db")
        if group is ToolGroup.BACKTEST:
            return has("backtest_service")
        if group is ToolGroup.OPTIMIZER:
            return has("mcp_backtest_runner") and has("mcp_sweep_repo")
        if group is ToolGroup.DEBUG:
            return has("debug_trace_recorder")
        # SYMBOLS uses an importable data module (no app.state dep); ADVANCED is OFF.
        return True

    async def enable(self) -> None:
        cfg = await self.config_repo.get()
        # Start the transport FIRST; only persist enabled=True if it actually
        # comes up. This prevents a "running-but-dead" half-state where the DB
        # says enabled but /mcp/rpc 503s. _start_transport degrades to
        # server=None on failure, so we can detect it.
        if self.server is None:
            await self._start_transport(cfg)
        if self.server is None:
            raise RuntimeError(f"mcp transport failed to start: {self.last_error}")
        # Dry-connect self-test (FR-003): the just-built server must initialize +
        # list tools cleanly before we persist enabled=True. If it can't, tear
        # down and stay OFF rather than advertise a broken server.
        if not self.server.self_test():
            await self._stop_transport()
            self.server = None
            raise RuntimeError("mcp self-test failed; staying disabled")
        await self.config_repo.update({"enabled": True}, expected_row_version=cfg.row_version)

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
        # Cancel any in-flight async sweep tasks so they don't keep running
        # against the DB after the server is "off" (and so re-enable's
        # recover_interrupted doesn't race a still-live task). _execute_sweep
        # converts CancelledError → finish_job("cancelled").
        registry = getattr(self._app.state, "mcp_sweep_tasks", None)
        if registry:
            tasks = list(registry.values())
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            registry.clear()
        # Stop the SLI poll task.
        if self._sli_task is not None:
            self._sli_task.cancel()
            try:
                await self._sli_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._sli_task = None
        self.breaker = None
        self.db_floor = None
        self._app.state.mcp_db_floor = None
        if self._transport_cm is not None:
            try:
                await self._transport_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.exception("mcp_transport_stop_failed")
            self._transport_cm = None
        if self.server is not None:
            await self.server.shutdown()
            self.server = None
        # Stop the audit writer task explicitly (server.shutdown also stops it,
        # but on a PARTIAL start self.server may be None while the writer task is
        # already running — stop it here so it can never be orphaned/leaked).
        if self.audit_writer is not None:
            try:
                await self.audit_writer.shutdown()
            except Exception:  # noqa: BLE001
                logger.exception("mcp_audit_writer_stop_failed")
            self.audit_writer = None
        # Release MCP leadership so another worker can take over.
        if self.leader is not None:
            try:
                await self.leader.release()
            except Exception:  # noqa: BLE001
                logger.exception("mcp_leader_release_failed")
            self.leader = None

    async def shutdown(self) -> None:
        await self._stop_transport()


def register_mcp(app: Any) -> None:
    """create_app() body: permanent indirection mount + control-plane router.

    Reads nothing; opens no DB connection.
    """
    app.state.mcp_asgi = None
    app.state.mcp_server = None
    app.state.mcp_manager = None
    app.mount(MCP_RPC_PATH, _Indirection(app))

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
