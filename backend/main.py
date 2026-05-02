"""FastAPI application with CORS, CSP, CSRF protection — TASK-001."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.event_bus import EventBus
from backend.persistence import AnalysisDB
from backend.services.analysis_service import AnalysisService
from backend.services.config_service import ConfigService
from backend.services.memory_service import MemoryService
from backend.ws_manager import WSManager


class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        response = await call_next(request)
        csp_connect = os.environ.get(
            "WEB_CSP_CONNECT_SRC",
            "'self' ws://localhost:* wss://localhost:*",
        )
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data:; font-src 'self'; connect-src {csp_connect}; "
            f"frame-ancestors 'none'"
        )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            if request.headers.get("X-Requested-With") != "XMLHttpRequest":
                return Response(
                    content='{"detail":"Missing X-Requested-With header","code":"CSRF_REQUIRED"}',
                    status_code=403,
                    media_type="application/json",
                )
        return await call_next(request)


def create_app() -> FastAPI:
    db_path = os.environ.get(
        "TRADINGAGENTS_WEB_DB_PATH", "~/.tradingagents/cache/web_runs.db"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        db = AnalysisDB(db_path=db_path)
        db.recover_orphans()
        event_bus = EventBus(loop=loop)
        ws_manager = WSManager(event_bus=event_bus)
        config_service = ConfigService(db=db)

        app.state.db = db
        app.state.event_bus = event_bus
        app.state.ws_manager = ws_manager
        app.state.config_service = config_service
        app.state.memory_service = MemoryService()
        app.state.analysis_service = AnalysisService(
            persistence=db,
            event_bus=event_bus,
            ws_manager=ws_manager,
            config_service=config_service,
        )
        yield
        await app.state.analysis_service.shutdown()
        db.close()

    app = FastAPI(title="TradingAgents Web API", lifespan=lifespan)

    cors_origin = os.environ.get("WEB_CORS_ORIGIN", "http://localhost:5173")
    cors_origins = [o.strip() for o in cors_origin.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(CSPMiddleware)

    from backend.routers.config import router as config_router
    from backend.routers.models import router as models_router
    from backend.routers.checkpoints import router as checkpoints_router
    from backend.routers.memory import router as memory_router
    from backend.routers.analysis import router as analysis_router
    from backend.routers.ws import router as ws_router

    app.include_router(config_router, prefix="/api/v1")
    app.include_router(models_router, prefix="/api/v1")
    app.include_router(checkpoints_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(ws_router)

    @app.get("/api/v1/health")
    async def health(request: Request):
        db_status = request.app.state.db.health_check()
        return {"status": "ok", "db": db_status}

    return app
