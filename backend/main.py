"""FastAPI application with CORS, CSP, CSRF protection — TASK-001."""

from __future__ import annotations

import asyncio
from pathlib import Path
import concurrent.futures
import gc
import logging
import json as _json
import os
import re as _re
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.event_bus import EventBus
from backend.async_persistence import AsyncAnalysisDB
from backend.observability import ObservabilityMiddleware, configure_structured_logging, metrics
from backend.services.analysis_service import AnalysisService
from backend.services.config_service import ConfigService
from backend.services.memory_service import MemoryService
from backend.services.scanner_service import ScannerService
from tradingagents.llm_clients import configure_llm_concurrency, configure_llm_min_spacing
from tradingagents.dataflows.coingecko_data import get_coingecko_status
from backend.ws_manager import WSManager


_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")
load_dotenv(_project_root / ".env.enterprise", override=False)

logger = logging.getLogger(__name__)


def _validated_int(name: str, default: int, min_val: int, max_val: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a valid integer")
    if not (min_val <= val <= max_val):
        raise ValueError(f"{name}={val} out of range [{min_val}, {max_val}]")
    return val


_CSP_CONNECT = os.environ.get(
    "WEB_CSP_CONNECT_SRC",
    "'self'",
)
_CSP_CONNECT = _re.sub(r"[^\x20-\x7E]|[;\n\r]", "", _CSP_CONNECT)
_CSP_CONNECT = " ".join(
    t for t in _CSP_CONNECT.split()
    if _re.match(r"^('[\w-]+'|[\w:+.\-]+://[\w:.\-/?#@%=&+,*!]+)$", t)
) or "'self'"
_CSP_HEADER = (
    f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    f"img-src 'self' data:; font-src 'self'; connect-src {_CSP_CONNECT}; "
    f"frame-ancestors 'none'"
)
_CSP_HEADER_BYTES = _CSP_HEADER.encode()

_CSRF_BODY = b'{"detail":"Missing X-Requested-With header","code":"CSRF_REQUIRED"}'


class CSPCSRFMiddleware:
    """Pure ASGI middleware combining CSP header injection and CSRF check."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CSRF check for mutating methods
        if scope["method"] in {"POST", "PATCH", "PUT", "DELETE"}:
            headers = dict(scope.get("headers", []))
            if headers.get(b"x-requested-with") != b"XMLHttpRequest":
                await send({
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"content-security-policy", _CSP_HEADER_BYTES],
                    ],
                })
                await send({"type": "http.response.body", "body": _CSRF_BODY})
                return

        # Inject security headers into every response
        async def send_with_csp(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"content-security-policy", _CSP_HEADER_BYTES])
                headers.append([b"x-content-type-options", b"nosniff"])
                headers.append([b"x-frame-options", b"DENY"])
                headers.append([b"strict-transport-security", b"max-age=63072000; includeSubDomains"])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_csp)


_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


class ContentSizeLimitMiddleware:
    """Reject HTTP requests with Content-Length exceeding the limit."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            cl = headers.get(b"content-length")
            if cl is not None:
                try:
                    if int(cl) > _MAX_BODY_BYTES:
                        await send({"type": "http.response.start", "status": 413, "headers": [[b"content-type", b"application/json"]]})
                        await send({"type": "http.response.body", "body": b'{"detail":"Request body too large"}'})
                        return
                except (ValueError, TypeError):
                    pass
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    dsn = os.environ.get("DATABASE_URL")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        if os.environ.get("LOG_FORMAT", "").lower() == "json":
            configure_structured_logging(log_level)
        else:
            logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

        loop = asyncio.get_running_loop()

        _default_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=_validated_int("THREADPOOL_MAX_WORKERS", 32, 4, 128),
            thread_name_prefix="default",
        )
        loop.set_default_executor(_default_executor)
        logger.info("Default thread pool: %d workers", _default_executor._max_workers)

        db = AsyncAnalysisDB(dsn=dsn)
        await db.connect()
        try:
            await db.recover_orphans()
        except Exception:
            await db.close()
            raise
        event_bus = EventBus(loop=loop)
        ws_manager = WSManager(event_bus=event_bus)
        config_service = ConfigService(db=db)

        llm_max = _validated_int("LLM_MAX_CONCURRENT", 0, 0, 1000)
        configure_llm_concurrency(llm_max)
        llm_spacing = _validated_int("LLM_MIN_SPACING_MS", 0, 0, 60000)
        configure_llm_min_spacing(llm_spacing)

        app.state.db = db
        app.state.event_bus = event_bus
        app.state.ws_manager = ws_manager
        app.state.config_service = config_service
        app.state.memory_service = MemoryService()
        app.state.cors_origins = cors_origins
        app.state.analysis_service = AnalysisService(
            persistence=db,
            event_bus=event_bus,
            ws_manager=ws_manager,
            config_service=config_service,
        )
        app.state.scanner_service = ScannerService(
            analysis_service=app.state.analysis_service,
            db=db,
            ws_manager=ws_manager,
        )

        from backend.services.strategy_service import StrategyService
        app.state.strategy_service = StrategyService(db=db)
        await app.state.scanner_service.resume_incomplete_scans()

        from backend.services.scan_scheduler_service import ScanSchedulerService
        scheduler_service = ScanSchedulerService(
            scanner_service=app.state.scanner_service,
            db=db,
            config_service=config_service,
        )
        app.state.scheduler_service = scheduler_service
        await scheduler_service.recover_on_startup()
        scheduler_service.start()

        async def _event_loop_watchdog():
            _loop = asyncio.get_running_loop()
            while True:
                start = _loop.time()
                await asyncio.sleep(0.1)
                drift = _loop.time() - start - 0.1
                if drift > 0.5:
                    logger.warning("Event loop stall: %.0fms drift", drift * 1000)

        _watchdog_task = asyncio.create_task(_event_loop_watchdog())

        # Tune GC to reduce stop-the-world pauses that stall the event loop.
        # Raise gen2 threshold so full collections happen less frequently;
        # large LLM response objects accumulate in gen2 during analysis scans.
        gc.set_threshold(700, 10, 50)
        gc.freeze()  # freeze current objects so GC skips them in gen0/gen1 sweeps
        logger.info("GC tuned: thresholds=%s, frozen=%d objects", gc.get_threshold(), gc.get_freeze_count())

        # Trading accounts service (optional — only if encryption key is configured)
        from backend.services.accounts_service import AccountsService
        if os.environ.get("ACCOUNTS_ENCRYPTION_KEY"):
            from backend.crypto import validate_encryption_key
            validate_encryption_key()
            from backend.services.account_ws_manager import AccountWSManager
            account_ws_mgr = AccountWSManager(db=db)
            app.state.account_ws_manager = account_ws_mgr
            app.state.accounts_service = AccountsService(db=db, ws_manager=account_ws_mgr)
            app.state.scanner_service._accounts = app.state.accounts_service
            await account_ws_mgr.start()

            from backend.scheduler import SnapshotScheduler
            scheduler = SnapshotScheduler(
                snapshot_fn=app.state.accounts_service.take_all_hf_snapshots,
                cleanup_fn=app.state.accounts_service.auto_cleanup_old_snapshots,
            )
            await scheduler.start()
            app.state.snapshot_scheduler = scheduler

            from backend.services.close_positions_service import ClosePositionsService
            app.state.close_positions_service = ClosePositionsService(
                db=db, accounts_service=app.state.accounts_service, ws_manager=account_ws_mgr,
            )
            app.state.scanner_service._close_svc = app.state.close_positions_service

            from backend.services.close_rule_evaluator import CloseRuleEvaluator
            rule_evaluator = CloseRuleEvaluator(
                close_service=app.state.close_positions_service,
                accounts_service=app.state.accounts_service,
                db=db,
            )
            await rule_evaluator.start()
            app.state.rule_evaluator = rule_evaluator
            account_ws_mgr.register_wallet_listener(rule_evaluator.on_wallet_update)
            logger.info("CloseRuleEvaluator subscribed to WS wallet events")

            from backend.services.cycle_repository import CycleRepository
            from backend.services.trading_cycle_engine import TradingCycleEngine
            cycle_repo = CycleRepository(db._pool)
            cycle_engine = TradingCycleEngine(
                cycle_repo=cycle_repo,
                accounts_svc=app.state.accounts_service,
                close_positions_svc=app.state.close_positions_service,
                db=db,
                ws_manager=account_ws_mgr,
            )

            async def _broadcast_cycle_event(event_type: str, payload: dict) -> None:
                if account_ws_mgr and event_type in ("cycle.status_change", "cycle.progress"):
                    await account_ws_mgr.broadcast_event({
                        "type": event_type, **payload,
                    })

            cycle_engine.register_lifecycle_callback(_broadcast_cycle_event)
            await cycle_engine.start()
            app.state.cycle_engine = cycle_engine
            rule_evaluator.set_cycle_callback(cycle_engine.on_rule_triggered)
            rule_evaluator.set_cycle_repo(cycle_repo)

            # AI Account Manager service
            from backend.services.ai_manager_market_data import MarketDataCache
            market_data_cache = MarketDataCache()
            await market_data_cache.start()

            from backend.services.ai_account_manager_service import AIAccountManagerService
            ai_manager_service = AIAccountManagerService.create({
                "accounts_service": app.state.accounts_service,
                "close_positions_service": app.state.close_positions_service,
                "account_ws_manager": account_ws_mgr,
                "db_pool": db._pool,
                "market_data_cache": market_data_cache,
            })
            await ai_manager_service.start()
            app.state.ai_manager_service = ai_manager_service
            app.state.market_data_cache = market_data_cache
            app.state.scanner_service._ai_manager_service = ai_manager_service
            if getattr(app.state, "scheduler_service", None):
                app.state.scheduler_service.set_ai_manager_service(ai_manager_service)

            # Wire LLM callable for AI Manager decisions
            from backend.services.ai_manager_llm_provider import create_llm_callable
            llm_callable = create_llm_callable()
            if llm_callable:
                ai_manager_service._llm_callable = llm_callable
                ai_manager_service._pattern_llm_callable = llm_callable
                logger.info("AI Manager LLM callable configured")

            from backend.services.trade_repository import TradeRepository
            from backend.services.trade_service import TradeService
            trade_repo = TradeRepository(db=db)
            trade_service = TradeService(
                db=db,
                trade_repo=trade_repo,
                accounts_service=app.state.accounts_service,
                ws_manager=account_ws_mgr,
            )
            app.state.trade_repo = trade_repo
            app.state.trade_service = trade_service
            app.state.accounts_service.set_trade_dependencies(trade_repo, trade_service)
            app.state.close_positions_service.set_trade_service(trade_service)

            from backend.services.position_reconciler import PositionReconciler
            position_reconciler = PositionReconciler(
                db=db,
                accounts_service=app.state.accounts_service,
                trade_service=trade_service,
                ws_manager=account_ws_mgr,
            )
            await position_reconciler.start()
            app.state.position_reconciler = position_reconciler
        else:
            app.state.accounts_service = None
            app.state.account_ws_manager = None
            app.state.snapshot_scheduler = None
            app.state.close_positions_service = None
            app.state.rule_evaluator = None
            app.state.cycle_engine = None
            app.state.trade_repo = None
            app.state.trade_service = None
            app.state.position_reconciler = None

        logger.info("app_ready: all services initialised")

        yield

        _SHUTDOWN_TIMEOUT = 15.0

        async def _safe_shutdown(name: str, coro) -> None:
            try:
                await asyncio.wait_for(coro, timeout=_SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error("shutdown_timeout: %s exceeded %.0fs", name, _SHUTDOWN_TIMEOUT)
            except Exception:
                logger.exception("shutdown_step_failed: %s", name)

        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass
        await _safe_shutdown("scheduler_service", app.state.scheduler_service.shutdown())
        if getattr(app.state, "ai_manager_service", None):
            await _safe_shutdown("ai_manager_service", app.state.ai_manager_service.shutdown())
            from backend.services.ai_manager_llm_provider import close_llm_clients
            await _safe_shutdown("ai_manager_llm_clients", close_llm_clients())
        if getattr(app.state, "market_data_cache", None):
            await _safe_shutdown("market_data_cache", app.state.market_data_cache.stop())
        if getattr(app.state, "rule_evaluator", None):
            await _safe_shutdown("rule_evaluator", app.state.rule_evaluator.shutdown())
        if getattr(app.state, "cycle_engine", None):
            await _safe_shutdown("cycle_engine", app.state.cycle_engine.shutdown())
        if getattr(app.state, "position_reconciler", None):
            await _safe_shutdown("position_reconciler", app.state.position_reconciler.shutdown())
        if app.state.snapshot_scheduler:
            await _safe_shutdown("snapshot_scheduler", app.state.snapshot_scheduler.shutdown())
            await asyncio.sleep(0.5)
        if app.state.account_ws_manager:
            await _safe_shutdown("account_ws_manager", app.state.account_ws_manager.shutdown())
        if app.state.accounts_service:
            await _safe_shutdown("accounts_service", app.state.accounts_service.shutdown())
        await _safe_shutdown("scanner_service", app.state.scanner_service.shutdown())
        await _safe_shutdown("analysis_service", app.state.analysis_service.shutdown())
        await _safe_shutdown("ws_manager", ws_manager.shutdown())
        from tradingagents.graph.parallel_debate import shutdown_debate_executor
        shutdown_debate_executor()
        _default_executor.shutdown(wait=False, cancel_futures=True)
        await asyncio.sleep(1)
        await db.close()

    app = FastAPI(title="TradingAgents Web API", lifespan=lifespan)

    cors_origin = os.environ.get("WEB_CORS_ORIGIN", "http://localhost:5177,http://localhost:5178,http://localhost:5179")
    cors_origins = [o.strip() for o in cors_origin.split(",") if o.strip()]
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(ContentSizeLimitMiddleware)
    app.add_middleware(CSPCSRFMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )

    from backend.routers.config import router as config_router
    from backend.routers.models import router as models_router
    from backend.routers.checkpoints import router as checkpoints_router
    from backend.routers.memory import router as memory_router
    from backend.routers.analysis import router as analysis_router
    from backend.routers.symbols import router as symbols_router
    from backend.routers.scanner import router as scanner_router
    from backend.routers.ws import router as ws_router
    from backend.routers.ws_accounts import router as ws_accounts_router
    from backend.routers.accounts import router as accounts_router
    from backend.routers.trades import router as trades_router
    from backend.routers.portfolio import router as portfolio_router
    from backend.routers.analytics import router as analytics_router
    from backend.routers.strategies import router as strategies_router
    from backend.routers.scheduled_scans import router as scheduled_scans_router
    from backend.routers.close_positions import router as close_positions_router
    from backend.routers.ai_manager import router as ai_manager_router

    app.include_router(portfolio_router, prefix="/api/v1")
    app.include_router(analytics_router, prefix="/api/v1")
    app.include_router(strategies_router, prefix="/api/v1")
    app.include_router(config_router, prefix="/api/v1")
    app.include_router(models_router, prefix="/api/v1")
    app.include_router(checkpoints_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(symbols_router, prefix="/api/v1")
    app.include_router(scanner_router, prefix="/api/v1")
    app.include_router(scheduled_scans_router, prefix="/api/v1")
    app.include_router(accounts_router, prefix="/api/v1")
    app.include_router(trades_router, prefix="/api/v1")
    app.include_router(close_positions_router, prefix="/api/v1")
    app.include_router(ai_manager_router, prefix="/api/v1")
    from backend.routers.trading_cycles import router as trading_cycles_router
    app.include_router(trading_cycles_router, prefix="/api/v1")
    app.include_router(ws_router)
    app.include_router(ws_accounts_router)

    @app.get("/api/v1/healthz")
    async def healthz():
        """Liveness probe — returns 200 if the process is alive."""
        return Response(content='{"status":"alive"}', media_type="application/json")

    @app.get("/metrics")
    async def prometheus_metrics():
        """Prometheus-compatible metrics endpoint."""
        return Response(content=metrics.prometheus_text(), media_type="text/plain; charset=utf-8")

    @app.get("/api/v1/health")
    async def health(request: Request):
        db_ok = request.app.state.db.is_healthy()
        svc = request.app.state.analysis_service
        active = sum(1 for r in svc._active_runs.values() if r.get("status") == "running")
        cap = svc.max_concurrent
        status = "ok" if db_ok else "degraded"
        if active > cap * 0.75:
            status = "degraded"
        body = {
            "status": status,
            "db": "ok" if db_ok else "unavailable",
            "analyses_active": active,
            "analyses_max": cap,
            "coingecko": get_coingecko_status(),
        }
        status_code = 503 if status == "degraded" else 200
        return Response(
            content=_json.dumps(body),
            status_code=status_code,
            media_type="application/json",
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", extra={"path": request.url.path, "method": request.method, "exc_type": type(exc).__name__}, exc_info=True)
        return Response(
            content='{"detail":"Internal server error","code":"INTERNAL_ERROR"}',
            status_code=500,
            media_type="application/json",
        )

    return app
