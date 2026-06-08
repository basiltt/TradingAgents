"""FastAPI application with CORS, CSP, CSRF protection — TASK-001."""

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import json as _json
import logging
import os
import re as _re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.async_persistence import AsyncAnalysisDB
from backend.event_bus import EventBus
from backend.observability import ObservabilityMiddleware, configure_structured_logging, metrics
from backend.services.analysis_service import AnalysisService
from backend.services.config_service import ConfigService
from backend.services.memory_service import MemoryService
from backend.services.scanner_service import ScannerService
from backend.ws_manager import WSManager
from tradingagents.dataflows.coingecko_data import get_coingecko_status
from tradingagents.llm_clients import (
    configure_llm_concurrency,
    configure_llm_concurrency_async,
    configure_llm_min_spacing,
)

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
        raise ValueError(f"{name}={raw!r} is not a valid integer") from None
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

# The MCP data-plane mount (/mcp/rpc and its sub-paths) is intentionally exempt
# from the X-Requested-With CSRF check: it is a non-browser bridge endpoint with
# its own defenses — a bearer-token authenticator plus a loopback Host/Origin
# allowlist (DNS-rebinding defense) in backend/mcp/core/transport.py. Any genuine
# cross-site browser request would carry a non-loopback Origin and be rejected by
# that guard, so the app-level CSRF header would only block legitimate MCP clients
# (Claude Code, mcp-remote) that cannot set arbitrary headers. This matches the
# "CSRF-exempt" data-plane contract in plans/mcp-server/00-plan-summary.md.
_CSRF_EXEMPT_PREFIX = "/mcp/rpc"


class CSPCSRFMiddleware:
    """Pure ASGI middleware combining CSP header injection and CSRF check."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CSRF check for mutating methods (the MCP data-plane is exempt — see above)
        if scope["method"] in {"POST", "PATCH", "PUT", "DELETE"} and not scope.get(
            "path", ""
        ).startswith(_CSRF_EXEMPT_PREFIX):
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

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
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

            # Guard against chunked encoding bypass (no Content-Length header)
            accumulated = 0

            async def size_limited_receive() -> dict:
                nonlocal accumulated
                msg = await receive()
                if msg.get("type") == "http.request":
                    body = msg.get("body", b"")
                    accumulated += len(body)
                    if accumulated > _MAX_BODY_BYTES:
                        raise ValueError("Request body too large")
                return msg

            try:
                await self.app(scope, size_limited_receive, send)
            except ValueError as e:
                if "too large" in str(e):
                    await send({"type": "http.response.start", "status": 413, "headers": [[b"content-type", b"application/json"]]})
                    await send({"type": "http.response.body", "body": b'{"detail":"Request body too large"}'})
                else:
                    raise
            return
        await self.app(scope, receive, send)


def _mcp_health_substatus(app: FastAPI) -> dict:
    """MCP sub-status for /api/v1/health (NFR-010). Pure read of app.state — a
    degraded/off/errored MCP must NEVER change the main health status code."""
    mgr = getattr(app.state, "mcp_manager", None)
    if mgr is None:
        return {"state": "absent"}
    running = getattr(app.state, "mcp_server", None) is not None
    last_error = getattr(mgr, "last_error", None)
    return {
        "state": "running" if running else "off",
        "error": last_error,
    }


def create_app() -> FastAPI:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL environment variable is required")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state._ready = False
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        if os.environ.get("LOG_FORMAT", "").lower() == "json":
            configure_structured_logging(log_level)
        else:
            logging.basicConfig(
                level=getattr(logging, log_level, logging.INFO),
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                force=True,
            )

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
        # Mirror the SAME limit onto the async path. LLM_MAX_CONCURRENT=0 means UNLIMITED by
        # design (pay-as-you-go plans have no concurrency cap), so the async path is unlimited
        # too when unset — identical provider pressure policy to the sync path. Operators who
        # DO have a provider concurrency limit set LLM_MAX_CONCURRENT and it applies to both.
        configure_llm_concurrency_async(llm_max)
        llm_spacing = _validated_int("LLM_MIN_SPACING_MS", 0, 0, 60000)
        configure_llm_min_spacing(llm_spacing)

        app.state.db = db
        # Debug tracing is an OPTIONAL forensics feature. Its router (503 when absent)
        # and the scanner (`if self._debug_recorder is not None`) are both designed to
        # tolerate a missing recorder, so a failure here must NEVER abort trading
        # startup — degrade to None and continue, mirroring backtest_service recovery.
        debug_recorder = None
        try:
            from backend.services.debug_trace_recorder import DebugTraceRecorder
            from backend.services.debug_trace_repository import DebugTraceRepository
            debug_repo = DebugTraceRepository(db.pool)
            debug_recorder = DebugTraceRecorder(debug_repo)
            await debug_recorder.start()
        except Exception:
            logger.exception("debug_trace_recorder_init_failed")
            debug_recorder = None
        app.state.debug_trace_recorder = debug_recorder
        app.state.event_bus = event_bus
        app.state.ws_manager = ws_manager
        app.state.config_service = config_service
        app.state.memory_service = MemoryService()

        from backend.services.signal_analytics_service import SignalAnalyticsService
        app.state.signal_analytics_service = SignalAnalyticsService(db=db)
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
            debug_recorder=debug_recorder,
        )

        # Sector classification service (CoinGecko + LLM + DB cache)
        from backend.services.ai_manager_llm_provider import create_llm_callable
        from backend.services.sector_service import SectorService
        _sector_llm, _ = create_llm_callable()
        sector_service = SectorService(db.pool, llm_callable=_sector_llm)
        await sector_service.load_cache()
        app.state.sector_service = sector_service
        app.state.scanner_service._sector_service = sector_service

        from backend.services.strategy_service import StrategyService
        app.state.strategy_service = StrategyService(db=db)

        # Backtesting service (always-on, no credentials needed)
        from backend.services.backtest_service import BacktestService
        from backend.services.kline_cache_service import KlineCacheService
        app.state.kline_cache_service = KlineCacheService(db=db)
        app.state.backtest_service = BacktestService(
            db=db, kline_cache=app.state.kline_cache_service,
        )
        # Wire the kline cache into the scanner for the Regime Multi-Strategy
        # feature (BTC regime + MR-mean fetches). The scanner is constructed
        # before the cache exists, so attach it here.
        app.state.scanner_service._kline_cache = app.state.kline_cache_service
        # The MCP optimizer's BacktestRunner adapter — BacktestService.run_one
        # satisfies the Protocol, so the in-process sweep path uses the REAL
        # engine (not a stub). Read lazily by ctx.services.backtest_runner.
        app.state.mcp_backtest_runner = app.state.backtest_service
        # Recover any backtests left 'running'/'pending' by a previous process.
        try:
            await app.state.backtest_service.recover_stale_runs()
        except Exception:
            logger.exception("backtest_stale_recovery_failed")

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
            account_ws_mgr.set_accounts_service(app.state.accounts_service)
            app.state.scanner_service._accounts = app.state.accounts_service
            # ONE shared per-(account,symbol) lock registry across the AutoTrade
            # executor, the AI manager, and the close evaluator — so they can never
            # act on the same position concurrently (double/opposite placement,
            # close-vs-open races). Must be created before those services so they
            # all bind to the SAME instance.
            from backend.services.position_lock_registry import PositionLockRegistry
            app.state.position_lock_registry = PositionLockRegistry()
            app.state.scanner_service._position_lock_registry = app.state.position_lock_registry
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
                # bind to the SHARED registry (not a throwaway) so AI-manager
                # position locks are visible to the auto-trade executor.
                "position_lock_registry": app.state.position_lock_registry,
            })
            await ai_manager_service.start()
            app.state.ai_manager_service = ai_manager_service
            app.state.market_data_cache = market_data_cache
            app.state.scanner_service._ai_manager_service = ai_manager_service
            if getattr(app.state, "scheduler_service", None):
                app.state.scheduler_service.set_ai_manager_service(ai_manager_service)

            # Wire LLM callable for AI Manager decisions
            from backend.services.ai_manager_llm_provider import create_llm_callable
            llm_callable, resolved_model = create_llm_callable()
            if llm_callable:
                ai_manager_service._llm_callable = llm_callable
                ai_manager_service._pattern_llm_callable = llm_callable
                ai_manager_service._model_name = resolved_model
                logger.info("AI Manager LLM callable configured (model=%s)", resolved_model)

            from backend.services.decay_detector import DecayDetector
            from backend.services.signal_performance_service import SignalPerformanceMaterializer
            from backend.services.trade_repository import TradeRepository
            from backend.services.trade_service import TradeService
            trade_repo = TradeRepository(db=db)
            decay_detector = DecayDetector(db=db, ws_manager=account_ws_mgr)
            signal_perf = SignalPerformanceMaterializer(db=db, decay_detector=decay_detector)
            trade_service = TradeService(
                db=db,
                trade_repo=trade_repo,
                accounts_service=app.state.accounts_service,
                ws_manager=account_ws_mgr,
                signal_perf=signal_perf,
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

        # Regime classifier — always running, independent of accounts
        from backend.services.regime_classifier import RegimeClassifier
        regime_classifier = RegimeClassifier(db=db, llm_callable=None)

        async def _run_regime_classification() -> None:
            import asyncio as _asyncio
            import csv as _csv
            import io as _io
            import time as _time

            from tradingagents.dataflows.bybit_data import (
                get_bybit_klines,
                get_shared_circuit_breaker,
                get_shared_limiter,
            )

            pos_rows = await db.pool.fetch(
                "SELECT DISTINCT symbol FROM trades"
                " WHERE status IN ('open', 'partially_filled', 'closing', 'partially_closed')"
            )
            all_symbols = [r["symbol"] for r in pos_rows if r.get("symbol")]
            if not all_symbols:
                return

            # Drop symbols Bybit no longer lists on linear perpetuals (e.g. a coin we still
            # hold an open position in that has since been delisted). Public klines don't
            # exist for them, so a regime fetch would raise InvalidSymbolError and log a full
            # traceback every cycle. The held POSITION is unaffected — close-rule evaluation,
            # reconciliation, and closing all use the private account API and never touch this
            # public catalog. Regime classification simply can't run for a delisted symbol, so
            # skip it quietly. If the catalog is unavailable (empty set), keep all symbols
            # (normalize_bybit_symbol degrades gracefully in that case).
            from tradingagents.dataflows.bybit_data import get_valid_symbols
            try:
                _valid = get_valid_symbols()
            except Exception:
                _valid = set()
            if _valid:
                _listed = [s for s in all_symbols if s in _valid or f"1000{s}" in _valid]
                _delisted = [s for s in all_symbols if s not in _listed]
                if _delisted:
                    logger.info(
                        "regime_skip_delisted_symbols: %s no longer on Bybit linear perps "
                        "(open positions remain managed via the account API)",
                        ", ".join(sorted(_delisted)),
                    )
                all_symbols = _listed
            if not all_symbols:
                return

            _limiter = get_shared_limiter()
            _cb = get_shared_circuit_breaker()

            async def _fetch_candles(symbol: str, interval: str = "240", limit: int = 50) -> list:
                end_ms = int(_time.time() * 1000)
                start_ms = end_ms - (limit * int(interval) * 60 * 1000)
                loop = _asyncio.get_event_loop()
                csv_data = await loop.run_in_executor(
                    None,
                    lambda: get_bybit_klines(
                        symbol, interval, start_ms, end_ms,
                        None, _limiter, _cb,
                    ),
                )
                # Strip any truncation warning line before CSV header
                if csv_data.startswith("["):
                    csv_data = csv_data[csv_data.index("\n") + 1:]
                candles = []
                reader = _csv.DictReader(_io.StringIO(csv_data))
                for row in reader:
                    try:
                        candles.append({
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                        })
                    except (KeyError, ValueError):
                        pass
                return candles

            await regime_classifier.run_all(all_symbols, _fetch_candles)
            logger.info("regime_classification_complete", extra={"symbols": len(all_symbols)})

        from backend.scheduler import SnapshotScheduler as _SnapshotScheduler
        regime_scheduler = _SnapshotScheduler(regime_fn=_run_regime_classification)
        await regime_scheduler.start()
        app.state.regime_scheduler = regime_scheduler

        # MCP boot — AFTER migrations, stale-backtest recovery, and scanner-resume
        # (so the optional MCP server never delays live-trading startup). Reads the
        # persisted mcp_config; starts the transport only if enabled. Never raises.
        try:
            from backend.mcp.mount import mcp_boot
            await mcp_boot(app)
        except Exception:
            logger.exception("mcp_boot_call_failed")
            app.state.mcp_server = None

        logger.info("app_ready: all services initialised")
        app.state._ready = True

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
        # Drain the scanner FIRST: an in-flight auto-trade scan places trades THROUGH
        # accounts_service / ai_manager_service, so the producer must be cancelled and
        # awaited before those consumers are torn down — otherwise a running scan can
        # recreate a just-closed Bybit client and place an untracked trade during
        # shutdown (money-safety). scanner_service.shutdown() cancels + gathers all
        # in-flight scan tasks.
        await _safe_shutdown("scanner_service", app.state.scanner_service.shutdown())
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
        if getattr(app.state, "regime_scheduler", None):
            await _safe_shutdown("regime_scheduler", app.state.regime_scheduler.shutdown())
        if app.state.account_ws_manager:
            await _safe_shutdown("account_ws_manager", app.state.account_ws_manager.shutdown())
        if app.state.accounts_service:
            await _safe_shutdown("accounts_service", app.state.accounts_service.shutdown())
        if getattr(app.state, "debug_trace_recorder", None):
            await _safe_shutdown("debug_trace_recorder", app.state.debug_trace_recorder.shutdown())
        await _safe_shutdown("analysis_service", app.state.analysis_service.shutdown())
        await _safe_shutdown("backtest_service", app.state.backtest_service.shutdown())
        if getattr(app.state, "mcp_manager", None):
            await _safe_shutdown("mcp_manager", app.state.mcp_manager.shutdown())
        await _safe_shutdown("ws_manager", ws_manager.shutdown())
        from tradingagents.graph.parallel_debate import shutdown_debate_executor
        shutdown_debate_executor()
        _default_executor.shutdown(wait=False, cancel_futures=True)
        await asyncio.sleep(1)
        await db.close()

    app = FastAPI(title="TradingAgents Web API", lifespan=lifespan)

    cors_origin = os.environ.get("WEB_CORS_ORIGIN", "http://localhost:5177,http://localhost:5178,http://localhost:5179")
    cors_origins = [o.strip() for o in cors_origin.split(",") if o.strip()]
    if "*" in cors_origins:
        logger.warning("CORS wildcard '*' with allow_credentials is invalid — removing wildcard")
        cors_origins = [o for o in cors_origins if o != "*"]
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

    from backend.routers.accounts import router as accounts_router
    from backend.routers.ai_manager import router as ai_manager_router
    from backend.routers.analysis import router as analysis_router
    from backend.routers.analytics import router as analytics_router
    from backend.routers.backtest import router as backtest_router
    from backend.routers.checkpoints import router as checkpoints_router
    from backend.routers.close_positions import router as close_positions_router
    from backend.routers.config import router as config_router
    from backend.routers.memory import router as memory_router
    from backend.routers.models import router as models_router
    from backend.routers.portfolio import router as portfolio_router
    from backend.routers.scanner import router as scanner_router
    from backend.routers.scheduled_scans import router as scheduled_scans_router
    from backend.routers.signal_analytics import router as signal_analytics_router
    from backend.routers.strategies import router as strategies_router
    from backend.routers.symbols import router as symbols_router
    from backend.routers.trades import router as trades_router
    from backend.routers.ws import router as ws_router
    from backend.routers.ws_accounts import router as ws_accounts_router

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
    app.include_router(signal_analytics_router, prefix="/api/v1")
    app.include_router(backtest_router, prefix="/api/v1")
    from backend.routers.trading_cycles import router as trading_cycles_router
    app.include_router(trading_cycles_router, prefix="/api/v1")
    from backend.routers.debug import router as debug_router
    app.include_router(debug_router, prefix="/api/v1")
    from backend.routers.admin import router as admin_router
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(ws_router)
    app.include_router(ws_accounts_router)

    # MCP server (AI agent integration) — single integration seam. Installs the
    # permanent /mcp/rpc indirection mount (503 gate until enabled) + the
    # /api/v1/mcp/* control-plane router. Reads nothing; opens no DB connection.
    # Off by default; mcp_boot (in lifespan, after scanner-resume) decides whether
    # to start the transport. A failure here must never abort trading startup.
    try:
        from backend.mcp.mount import register_mcp
        register_mcp(app)
    except Exception:
        logger.exception("mcp_register_failed")

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
        if not getattr(request.app.state, "_ready", False):
            return Response(
                content=_json.dumps({"status": "starting"}),
                status_code=503,
                media_type="application/json",
            )
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
            # MCP sub-status (NFR-010): off/running/error — never affects the main
            # status code (a degraded/off MCP is not a 503 for the trading app).
            "mcp": _mcp_health_substatus(request.app),
        }
        status_code = 503 if not db_ok else 200
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
