"""FastAPI application with CORS, CSP, CSRF protection — TASK-001."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.event_bus import EventBus
from backend.persistence import AnalysisDB
from backend.services.analysis_service import AnalysisService
from backend.services.config_service import ConfigService
from backend.services.memory_service import MemoryService
from backend.services.scanner_service import ScannerService
from tradingagents.llm_clients import configure_llm_concurrency, configure_llm_min_spacing
from tradingagents.dataflows.coingecko_data import configure_coingecko_concurrency
from backend.ws_manager import WSManager


load_dotenv()
load_dotenv(".env.enterprise", override=False)


import re as _re

_CSP_CONNECT = os.environ.get(
    "WEB_CSP_CONNECT_SRC",
    "'self' ws://localhost:8877 wss://localhost:8877",
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

_MUTATING_METHODS = frozenset({b"POST", b"PATCH", b"PUT", b"DELETE"})
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
        if scope["method"].encode() in _MUTATING_METHODS:
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

        # Inject CSP header into every response
        async def send_with_csp(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"content-security-policy", _CSP_HEADER_BYTES])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_csp)


def create_app() -> FastAPI:
    dsn = os.environ.get("DATABASE_URL")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        db = AnalysisDB(dsn=dsn)
        try:
            db.recover_orphans()
        except Exception:
            db.close()
            raise
        event_bus = EventBus(loop=loop)
        ws_manager = WSManager(event_bus=event_bus)
        config_service = ConfigService(db=db)

        llm_max = int(os.environ.get("LLM_MAX_CONCURRENT", "0"))
        configure_llm_concurrency(llm_max)
        llm_spacing = int(os.environ.get("LLM_MIN_SPACING_MS", "0"))
        configure_llm_min_spacing(llm_spacing)
        configure_coingecko_concurrency(int(os.environ.get("COINGECKO_MAX_CONCURRENT", "2")))

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
        )

        from backend.services.strategy_service import StrategyService
        app.state.strategy_service = StrategyService(db=db)
        await app.state.scanner_service.resume_incomplete_scans()

        # Trading accounts service (optional — only if encryption key is configured)
        from backend.services.accounts_service import AccountsService
        if os.environ.get("ACCOUNTS_ENCRYPTION_KEY"):
            from backend.crypto import validate_encryption_key
            validate_encryption_key()
            from backend.services.account_ws_manager import AccountWSManager
            account_ws_mgr = AccountWSManager(db=db)
            app.state.account_ws_manager = account_ws_mgr
            app.state.accounts_service = AccountsService(db=db, ws_manager=account_ws_mgr)
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

            from backend.services.close_rule_evaluator import CloseRuleEvaluator
            rule_evaluator = CloseRuleEvaluator(
                close_service=app.state.close_positions_service,
                accounts_service=app.state.accounts_service,
                db=db,
            )
            await rule_evaluator.start()
            app.state.rule_evaluator = rule_evaluator
        else:
            app.state.accounts_service = None
            app.state.account_ws_manager = None
            app.state.snapshot_scheduler = None
            app.state.close_positions_service = None
            app.state.rule_evaluator = None

        yield
        if getattr(app.state, "rule_evaluator", None):
            await app.state.rule_evaluator.shutdown()
        if app.state.snapshot_scheduler:
            await app.state.snapshot_scheduler.shutdown()
            await asyncio.sleep(0.5)
        if app.state.account_ws_manager:
            await app.state.account_ws_manager.shutdown()
        if app.state.accounts_service:
            await app.state.accounts_service.shutdown()
        await app.state.scanner_service.shutdown()
        await app.state.analysis_service.shutdown()
        await ws_manager.shutdown()
        db.close()

    app = FastAPI(title="TradingAgents Web API", lifespan=lifespan)

    cors_origin = os.environ.get("WEB_CORS_ORIGIN", "http://localhost:5177")
    cors_origins = [o.strip() for o in cors_origin.split(",") if o.strip()]
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
    from backend.routers.accounts import router as accounts_router
    from backend.routers.portfolio import router as portfolio_router
    from backend.routers.ws_accounts import router as ws_accounts_router
    from backend.routers.analytics import router as analytics_router
    from backend.routers.strategies import router as strategies_router
    from backend.routers.close_positions import router as close_positions_router

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
    app.include_router(accounts_router, prefix="/api/v1")
    app.include_router(close_positions_router, prefix="/api/v1")
    app.include_router(ws_router)
    app.include_router(ws_accounts_router)

    @app.get("/api/v1/health")
    async def health(request: Request):
        db_status = await asyncio.to_thread(request.app.state.db.health_check)
        return {"status": "ok", "db": db_status}

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import logging
        logging.getLogger(__name__).error(f"Unhandled exception: {exc}", exc_info=True)
        return Response(
            content='{"detail":"Internal server error","code":"INTERNAL_ERROR"}',
            status_code=500,
            media_type="application/json",
        )

    return app
