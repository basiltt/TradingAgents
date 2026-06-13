"""Analysis service — manages analysis lifecycle with concurrency control — TASK-012."""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langgraph.errors import GraphRecursionError

from backend.async_persistence import AsyncAnalysisDB
from backend.callbacks import WebCallbackHandler
from backend.event_bus import EventBus
from backend.services.config_service import ConfigService
from backend.stream_parser import (
    ProgressEvent,
    ReportChunkEvent,
    StreamParserState,
    make_seq_counter,
    parse_stream_chunk,
)
from backend.utils import mask_secrets
from backend.validators import validate_backend_url
from backend.ws_manager import WSManager

logger = logging.getLogger(__name__)


def _async_graph_enabled() -> bool:
    """Feature flag for the async graph execution path (Phase 3 of the sync→async
    LLM conversion). Default OFF → the proven sync path (graph.stream in a thread pool)
    runs unchanged. Set TRADINGAGENTS_ASYNC_GRAPH=1 to drive the SAME graph via astream
    on the event loop (non-blocking LLM calls → real per-symbol concurrency). Read live
    (not cached) so it can be flipped without a code change."""
    return (os.environ.get("TRADINGAGENTS_ASYNC_GRAPH", "") or "").strip().lower() in ("1", "true", "yes", "on")

def _safe_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for env %s=%r, using default %d", name, raw, default)
        return default


_GRAPH_EXECUTOR_WORKERS = _safe_int_env("GRAPH_EXECUTOR_WORKERS", 8)
_graph_executor: concurrent.futures.ThreadPoolExecutor | None = None
_graph_executor_lock = threading.Lock()
_graph_executor_dead = False


def _get_graph_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _graph_executor, _graph_executor_dead
    with _graph_executor_lock:
        if _graph_executor is None or _graph_executor_dead:
            _graph_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=_GRAPH_EXECUTOR_WORKERS,
                thread_name_prefix="langgraph",
            )
            _graph_executor_dead = False
    return _graph_executor

DEFAULT_MAX_CONCURRENT = _safe_int_env("MAX_CONCURRENT_ANALYSES", 6)
_HARD_MAX_CONCURRENT = 15
_MAX_ZOMBIES = 3
_WALL_TIMEOUT = 30 * 60  # 30 minutes
_HARD_TIMEOUT = 35 * 60  # 35 minutes
_REPORT_KEYS = [
    "crypto_fundamentals_report", "sentiment_report", "market_report",
    "news_report", "fundamentals_report", "derivatives_report",
]
_WARNING_MARKERS = ("[ERROR]", "Data Quality Warning")


class AnalysisService:
    """Orchestrates analysis runs: lifecycle, concurrency limits, and persistence.

    Owns the in-memory registry of active runs, enforces the max-concurrent and
    zombie-thread limits, drives the trading graph, and exposes read APIs for
    run records, reports, and snapshots backed by the async DB.
    """

    def __init__(
        self,
        persistence: AsyncAnalysisDB,
        event_bus: EventBus,
        ws_manager: WSManager,
        config_service: ConfigService,
    ):
        self._db = persistence
        self._bus = event_bus
        self._ws = ws_manager
        self._config = config_service
        self._active_runs: Dict[str, Dict[str, Any]] = {}
        self._completion_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._zombie_count = 0
        self._shutting_down = False
        self._prefilter_limiter: Any = None
        self._prefilter_cb: Any = None
        self._prefilter_init_lock = threading.Lock()
        self._max_concurrent = DEFAULT_MAX_CONCURRENT

    @property
    def max_concurrent(self) -> int:
        """The current cap on simultaneously running analyses."""
        return self._max_concurrent

    def set_max_concurrent(self, value: int) -> None:
        """Set the max-concurrent cap, clamped to [1, hard maximum]."""
        self._max_concurrent = max(1, min(value, _HARD_MAX_CONCURRENT))

    async def start_analysis(self, request: Dict[str, Any]) -> str:
        """Start a new analysis run and return its run_id.

        Raises ConcurrencyLimitError if the server is shutting down, the
        max-concurrent cap is reached, or there are too many zombie threads.
        Persists the run row, registers it as active, and launches the analysis
        task in the background.
        """
        if self._shutting_down:
            raise ConcurrencyLimitError("Server is shutting down, not accepting new analyses.")
        async with self._lock:
            active = sum(1 for r in self._active_runs.values() if r["status"] == "running")
            if active >= self._max_concurrent:
                raise ConcurrencyLimitError(
                    f"Maximum {self._max_concurrent} concurrent analyses reached. "
                    f"Please wait for a running analysis to complete."
                )
            if self._zombie_count >= _MAX_ZOMBIES:
                raise ConcurrencyLimitError("Too many zombie threads. Please wait.")

            run_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            config_snapshot = self._build_config(request)
            safe_config = mask_secrets(config_snapshot)

            await self._db.insert_run({
                "run_id": run_id,
                "ticker": request["ticker"],
                "analysis_date": request["analysis_date"],
                "status": "running",
                "config": _safe_json(safe_config),
                "started_at": now,
                "asset_type": request.get("asset_type", "stock"),
            })

            self._active_runs[run_id] = {
                "status": "running",
                "cancel_event": threading.Event(),
                "task": None,
            }
            self._completion_events[run_id] = asyncio.Event()

        task = asyncio.create_task(self._run_analysis(run_id, request, config_snapshot))
        async with self._lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["task"] = task

        return run_id

    async def cancel_analysis(self, run_id: str) -> bool:
        """Request cancellation of a run; return True if cancelled or already done.

        Signals the run's cancel event and cancels its task if active. Falls back
        to the DB for unknown runs, returning False only if the run does not exist
        and True if it is no longer running.
        """
        async with self._lock:
            run = self._active_runs.get(run_id)
            if run:
                if run["status"] != "running":
                    return True
                run["cancel_event"].set()
                task = run.get("task")
                if task and not task.done():
                    task.cancel()
                return True

        db_run = await self._db.get_run(run_id)
        if not db_run:
            return False
        return db_run["status"] != "running"

    async def shutdown(self) -> None:
        """Drain active analyses within a 30s deadline, then cancel and shut down.

        Stops accepting new runs, signals all cancel events, waits up to 30
        seconds for in-flight runs to finish, force-cancels any stragglers, and
        tears down the graph executor.
        """
        self._shutting_down = True
        async with self._lock:
            for _rid, run in list(self._active_runs.items()):
                if run.get("cancel_event"):
                    run["cancel_event"].set()

        active = [r for r in self._active_runs.values() if r.get("status") == "running"]
        initial_active = len(active)
        if active:
            logger.info("Draining %d active analyses (30s deadline)...", initial_active)
            deadline = asyncio.get_running_loop().time() + 30
            while active and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(1)
                active = [r for r in self._active_runs.values() if r.get("status") == "running"]

        tasks_to_await = []
        async with self._lock:
            for _rid, run in list(self._active_runs.items()):
                task = run.get("task")
                if task and not task.done():
                    task.cancel()
                    tasks_to_await.append(task)
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        completed = initial_active - len(tasks_to_await)
        cancelled = len(tasks_to_await)
        logger.info("Shutdown complete: %d analyses completed, %d cancelled", completed, cancelled)
        global _graph_executor_dead
        if _graph_executor is not None:
            _graph_executor.shutdown(wait=False, cancel_futures=True)
            _graph_executor_dead = True

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return a run record (with config parsed to a dict), or None if absent."""
        run = await self._db.get_run(run_id)
        if run and isinstance(run.get("config"), str):
            try:
                run["config"] = json.loads(run["config"])
            except (json.JSONDecodeError, TypeError):
                run["config"] = {}
        return run

    async def wait_for_completion(self, run_id: str, timeout: float = 1800) -> Optional[Dict[str, Any]]:
        """Wait for an analysis to complete, returning the run record. Uses event-based
        notification instead of polling for near-zero latency."""
        async with self._lock:
            evt = self._completion_events.get(run_id)

        if evt:
            try:
                await asyncio.wait_for(evt.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        else:
            # Already finished or unknown run — fall back to DB check
            pass

        return await self.get_run(run_id)

    async def delete_run(self, run_id: str) -> bool:
        """Delete a single run record; return True if a row was removed."""
        return await self._db.delete_run(run_id)

    async def delete_all_runs(self) -> int:
        """Cancel all active runs then delete every run record; return the count deleted."""
        async with self._lock:
            run_ids = list(self._active_runs.keys())
        for rid in run_ids:
            await self.cancel_analysis(rid)
        return await self._db.delete_all_runs()

    async def list_runs(self, **kwargs) -> Dict[str, Any]:
        """Return a paginated list of runs with each config slimmed to the model fields.

        Filter/pagination kwargs are passed through to the DB. Each item's config
        is reduced to deep_think_llm and quick_think_llm.
        """
        result = await self._db.list_runs(**kwargs)
        for item in result.get("items", []):
            cfg = item.get("config")
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except (json.JSONDecodeError, TypeError):
                    cfg = {}
            if isinstance(cfg, dict):
                item["config"] = {
                    "deep_think_llm": cfg.get("deep_think_llm"),
                    "quick_think_llm": cfg.get("quick_think_llm"),
                }
            else:
                item["config"] = {}
        return result

    async def get_report(self, run_id: str) -> Optional[str]:
        """Return the run's report as joined Markdown, or None if no sections exist.

        Internal sections (those whose name starts with "_") are excluded.
        """
        sections = await self._db.get_report_sections(run_id)
        if not sections:
            return None
        return "\n\n---\n\n".join(
            s["content"] for s in sections
            if s["section"] != "_snapshot" and not s["section"].startswith("_")
        )

    async def get_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return the run's UI snapshot, reconciled with individually-saved sections.

        Prefers the stored _snapshot blob but always merges in DB report sections
        (which are authoritative and may post-date the blob), constructing a
        minimal snapshot if only sections exist. Returns None if there is nothing.
        """
        sections = await self._db.get_report_sections(run_id)
        snapshot = None
        for s in sections:
            if s["section"] == "_snapshot":
                try:
                    snapshot = json.loads(s["content"])
                except (json.JSONDecodeError, TypeError):
                    pass
                break

        # Build reports dict from individually-saved DB sections (always authoritative —
        # the snapshot blob may have been saved before all sections landed).
        db_reports = {s["section"]: s["content"] for s in sections if s["section"] != "_snapshot"}

        if snapshot is None:
            if not db_reports:
                return None
            # No snapshot blob yet but we have sections — construct a minimal one
            snapshot = {"agents": {}, "messages": [], "stats": None, "reports": db_reports}
        else:
            # Inject DB sections absent from the snapshot's reports dict.
            # DB sections written after the snapshot (e.g. _pm_signal, _trader_signal)
            # must be visible to the scanner; existing snapshot content is not overwritten.
            existing = snapshot.setdefault("reports", {})
            for key, content in db_reports.items():
                if key not in existing:
                    existing[key] = content
        return snapshot

    def _build_config(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from tradingagents.default_config import DEFAULT_CONFIG

        config = copy.deepcopy(DEFAULT_CONFIG)

        resolved = self._config.get_config()["resolved"]
        for k, v in resolved.items():
            if v != "***" and k != "backend_url":
                config[k] = v

        if request.get("provider"):
            config["llm_provider"] = request["provider"]
        if request.get("llm_api_key"):
            config["llm_api_key"] = request["llm_api_key"]
        if request.get("deep_think_llm"):
            config["deep_think_llm"] = request["deep_think_llm"]
        if request.get("quick_think_llm"):
            config["quick_think_llm"] = request["quick_think_llm"]
        if request.get("output_language"):
            config["output_language"] = request["output_language"]
        if request.get("data_vendors"):
            vendors = config["data_vendors"]
            if isinstance(vendors, dict):
                vendors.update(request["data_vendors"])
        if request.get("research_depth"):
            depth = request["research_depth"]
            config["max_debate_rounds"] = depth
            config["max_risk_discuss_rounds"] = depth
        if request.get("max_debate_rounds"):
            config["max_debate_rounds"] = request["max_debate_rounds"]
        if request.get("max_risk_discuss_rounds"):
            config["max_risk_discuss_rounds"] = request["max_risk_discuss_rounds"]
        if request.get("max_recur_limit"):
            config["max_recur_limit"] = request["max_recur_limit"]
        if request.get("checkpoint_enabled") is not None:
            config["checkpoint_enabled"] = request["checkpoint_enabled"]
        if request.get("prompt_cache_enabled") is not None:
            config["prompt_cache_enabled"] = request["prompt_cache_enabled"]

        if request.get("ta_prefilter_enabled") is not None:
            config["ta_prefilter_enabled"] = request["ta_prefilter_enabled"]
        if request.get("ta_prefilter_threshold") is not None:
            config["ta_prefilter_threshold"] = request["ta_prefilter_threshold"]

        config["workflow_mode"] = request.get("workflow_mode") or "deep_analysis"

        if request.get("agent_model_overrides"):
            config["agent_model_overrides"] = request["agent_model_overrides"]

        # Crypto-specific config
        if request.get("asset_type"):
            config["asset_type"] = request["asset_type"]
        if request.get("interval"):
            config["crypto_interval"] = request["interval"]

        backend_url = request.get("backend_url")
        if not backend_url:
            # Only fall back to the env var if the request's provider matches
            # the env provider (or no env provider is set). This prevents the
            # env proxy URL from overriding provider-native endpoints (e.g.
            # NVIDIA's integrate.api.nvidia.com) when the user switches providers.
            env_backend = os.getenv("TRADINGAGENTS_BACKEND_URL")
            if env_backend:
                env_provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER", "").lower()
                req_provider = (request.get("provider") or "").lower()
                if not req_provider or req_provider == env_provider:
                    backend_url = env_backend
        if backend_url:
            config["backend_url"] = validate_backend_url(backend_url, server_port=8000)

        return config

    async def _run_analysis(
        self, run_id: str, request: Dict[str, Any], config: Dict[str, Any],
    ) -> None:
        async with self._lock:
            cancel_event = self._active_runs.get(run_id, {}).get("cancel_event", threading.Event())

        try:
            self._bus.emit(run_id, ProgressEvent(phase="starting", detail="Initializing analysis"))

            callback = WebCallbackHandler(run_id=run_id, event_bus=self._bus)

            if _async_graph_enabled():
                # Flag ON: drive the graph via astream ON THE EVENT LOOP. The LLM calls
                # inside the agent nodes are non-blocking, so many symbols progress
                # concurrently without the 8-thread graph-executor ceiling.
                result = await asyncio.wait_for(
                    self._aexecute_graph(run_id, request, config, callback, cancel_event),
                    timeout=_WALL_TIMEOUT,
                )
            else:
                # Flag OFF (default): the proven sync path — graph runs in the thread pool.
                result = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        _get_graph_executor(), self._execute_graph,
                        run_id, request, config, callback, cancel_event,
                    ),
                    timeout=_WALL_TIMEOUT,
                )

            # Save snapshot before marking completed so the scanner never reads
            # a completed run without its reports already persisted in the DB.
            # The 0.2 s sleep is a best-effort yield so that in-flight emit_threadsafe
            # coroutines (scheduled via call_soon_threadsafe from background threads)
            # can land before the snapshot is captured.  It is not guaranteed — a slow
            # event-loop tick could still miss a late event — but that's tolerable here
            # because individual sections are also saved incrementally during streaming.
            await asyncio.sleep(0.2)
            await asyncio.to_thread(self._save_snapshot, run_id)

            if isinstance(result, dict):
                decision = result.get("final_trade_decision", "")
                if decision:
                    await self._db.save_report_section(run_id, "final_trade_decision", str(decision))

                data_warnings = []
                for rk in _REPORT_KEYS:
                    report_text = str(result.get(rk, ""))
                    if any(m in report_text for m in _WARNING_MARKERS):
                        for line in report_text.splitlines():
                            if any(m in line for m in _WARNING_MARKERS):
                                cleaned = line.strip()
                                if cleaned and cleaned not in data_warnings:
                                    data_warnings.append(cleaned)
                if data_warnings:
                    await self._db.save_report_section(
                        run_id, "data_warnings", json.dumps(data_warnings),
                    )

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            updated = await self._db.update_run_status(run_id, "completed", None, now)

            if updated:
                self._bus.emit(run_id, ProgressEvent(phase="completed", detail="Analysis complete"))

            # Signal completion immediately after DB status is terminal.
            # Don't wait for finally-block cleanup.
            evt = self._completion_events.get(run_id)
            if evt:
                evt.set()

        except asyncio.CancelledError:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            await self._db.update_run_status(run_id, "cancelled", "Cancelled by user", now)
            self._bus.emit(run_id, ProgressEvent(phase="cancelled", detail="Cancelled"))
            evt = self._completion_events.get(run_id)
            if evt:
                evt.set()

        except asyncio.TimeoutError:
            cancel_event.set()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            await self._db.update_run_status(run_id, "failed", "Wall-clock timeout (30min)", now)
            self._bus.emit(run_id, ProgressEvent(phase="failed", detail="Timeout"))
            evt = self._completion_events.get(run_id)
            if evt:
                evt.set()
            # Zombie tracking exists ONLY for the SYNC path: a timed-out graph keeps running
            # in the thread-pool executor (a real zombie holding a worker slot until
            # _HARD_TIMEOUT). The async path's asyncio.wait_for cancels the coroutine
            # cleanly on timeout — no lingering thread — so counting it as a zombie would
            # spuriously trip the _MAX_ZOMBIES gate and reject new analyses.
            if not _async_graph_enabled():
                async with self._lock:
                    self._zombie_count += 1
                asyncio.get_running_loop().call_later(
                    _HARD_TIMEOUT - _WALL_TIMEOUT,
                    lambda rid: asyncio.create_task(self._reclaim_zombie_async(rid)), run_id,
                )

        except Exception as e:
            logger.error("Analysis %s failed: %s", run_id, e, exc_info=True)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            await self._db.update_run_status(run_id, "failed", "Internal error occurred", now)
            self._bus.emit(run_id, ProgressEvent(phase="failed", detail="An error occurred"))
            evt = self._completion_events.get(run_id)
            if evt:
                evt.set()

        finally:
            # Save snapshot for error/cancel paths (success path already saved).
            try:
                await asyncio.to_thread(self._save_snapshot, run_id)
            except Exception:
                pass
            async with self._lock:
                self._active_runs.pop(run_id, None)
                self._completion_events.pop(run_id, None)

            self._bus.cleanup_run(run_id)

    def _save_snapshot(self, run_id: str) -> None:
        try:
            events = self._bus.get_snapshot(run_id)
            agents: Dict[str, str] = {}
            messages: list = []
            stats: Optional[Dict[str, Any]] = None
            reports: Dict[str, str] = {}

            for ev in events:
                t = ev.get("type")
                if t == "agent_status":
                    agents[ev.get("agent", "")] = ev.get("status", "")
                elif t == "message":
                    messages.append({
                        "sender": ev.get("sender", ""),
                        "content": ev.get("content", ""),
                        "seq": ev.get("seq", 0),
                    })
                elif t == "stats":
                    stats = {
                        "tokens_in": ev.get("tokens_in", 0),
                        "tokens_out": ev.get("tokens_out", 0),
                        "llm_calls": ev.get("llm_calls", 0),
                        "tool_calls": ev.get("tool_calls", 0),
                    }
                elif t == "report_chunk":
                    section = ev.get("section", "")
                    if section:
                        reports[section] = ev.get("content", "")

            snapshot = {
                "agents": agents,
                "messages": messages[-200:],
                "stats": stats,
                "reports": reports,
            }
            self._db.sync_save_report_section(run_id, "_snapshot", json.dumps(snapshot, default=str))
            for section, content in reports.items():
                self._db.sync_save_report_section(run_id, section, content)
        except Exception as exc:
            msg = str(exc).lower()
            if "pool" in msg or "shut" in msg or "closed" in msg:
                logger.debug("Skipped snapshot save for run %s — DB pool closed (shutdown)", run_id)
            else:
                logger.warning("Failed to save snapshot for run %s", run_id, exc_info=True)

    def _persist_signal_sections(self, run_id: str, last_chunk) -> None:
        """Save _pm_signal and _trader_signal JSON sections from the final graph chunk.

        Called from _execute_graph (runs in a thread), so sync DB calls are safe here.
        """
        if not last_chunk:
            return
        for key, section_name in (
            ("_pm_signal_data", "_pm_signal"),
            ("_trader_signal_data", "_trader_signal"),
        ):
            obj = last_chunk.get(key)
            if obj is None:
                continue
            try:
                if hasattr(obj, "model_dump_json"):
                    json_str = obj.model_dump_json()
                elif isinstance(obj, dict):
                    json_str = json.dumps(obj)
                else:
                    continue
                self._db.sync_save_report_section(run_id, section_name, json_str)
            except Exception:
                logger.warning(
                    "Failed to persist %s for run %s", section_name, run_id, exc_info=True
                )

    def _execute_graph(
        self, run_id: str, request: Dict[str, Any], config: Dict[str, Any],
        callback: Any, cancel_event: threading.Event,
    ) -> Optional[Dict[str, Any]]:
        prep = self._prepare_graph_run(run_id, request, config, callback)
        if prep.get("early_result") is not None:
            return prep["early_result"]
        graph, init_state, args = prep["graph"], prep["init_state"], prep["args"]
        last_chunk = self._drive_stream_sync(run_id, graph, init_state, args, config, cancel_event)
        self._persist_signal_sections(run_id, last_chunk)
        return last_chunk

    def _prepare_graph_run(
        self, run_id: str, request: Dict[str, Any], config: Dict[str, Any], callback: Any,
    ) -> Dict[str, Any]:
        """Shared graph SETUP for both the sync and async execution paths: TA pre-filter
        gate, graph construction, initial state, crypto price-context, and stream args.
        Returns {"early_result": dict} when analysis should short-circuit (prefilter skip
        or missing graph lib), else {"graph", "init_state", "args"}. This is SYNC and does
        blocking I/O (prefilter, memory log, Bybit price fetch) — the async caller runs it
        in a thread so the event loop is never stalled by setup."""
        # --- TA Pre-Filter gate (crypto only) ---
        if config.get("ta_prefilter_enabled") and config.get("asset_type") == "crypto":
            try:
                from tradingagents.dataflows.bybit_data import get_shared_circuit_breaker, get_shared_limiter
                from tradingagents.ta_prefilter import TAPreFilterEngine
                with self._prefilter_init_lock:
                    if self._prefilter_limiter is None:
                        self._prefilter_limiter = get_shared_limiter()
                        self._prefilter_cb = get_shared_circuit_breaker()
                threshold = config.get("ta_prefilter_threshold", 40)
                engine = TAPreFilterEngine(
                    symbol=request["ticker"],
                    interval=config.get("crypto_interval", "D"),
                    threshold=threshold,
                    cache={},
                    limiter=self._prefilter_limiter,
                    circuit_breaker=self._prefilter_cb,
                )
                pf_result = engine.run()
                # Emit prefilter result as a progress event
                self._bus.emit_threadsafe(run_id, ProgressEvent(
                    phase="ta_prefilter",
                    detail=pf_result.reason,
                ))
                if not pf_result.should_proceed:
                    # Save prefilter result and skip LLM analysis
                    self._db.sync_save_report_section(
                        run_id, "_ta_prefilter",
                        json.dumps(pf_result.to_dict()),
                    )
                    return {"early_result": {"final_trade_decision": f"SKIPPED by TA Pre-Filter: {pf_result.reason}",
                            "ta_prefilter": pf_result.to_dict()}}
            except Exception as exc:
                logger.warning("TA pre-filter error for %s, proceeding anyway: %s", request["ticker"], exc)

        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError:
            logger.warning("TradingAgentsGraph not available, using mock")
            return {"early_result": {"final_trade_decision": "Mock decision — TradingAgentsGraph not installed"}}

        # Determine analysts: user-specified > quick_trade defaults > full defaults
        explicit_analysts = request.get("analysts")
        if explicit_analysts:
            analyst_list = [a.value if hasattr(a, "value") else a for a in explicit_analysts]
        elif config.get("workflow_mode") == "quick_trade":
            qt_defaults = config.get("quick_trade_analysts", {})
            asset_key = "crypto" if config.get("asset_type") == "crypto" else "stock"
            analyst_list = qt_defaults.get(asset_key, (
                ["crypto_technical", "crypto_derivatives", "crypto_news"]
                if asset_key == "crypto"
                else ["market", "news"]
            ))
        else:
            analyst_list = (
                ["crypto_technical", "crypto_derivatives", "crypto_news", "crypto_fundamentals", "crypto_social"]
                if config.get("asset_type") == "crypto"
                else ["market", "news"]
            )

        graph = TradingAgentsGraph(
            config=config,
            selected_analysts=analyst_list,
        )

        past_context = ""
        if hasattr(graph, "memory_log"):
            try:
                past_context = graph.memory_log.get_past_context(request["ticker"])
            except Exception:
                logger.warning("Failed to load past trading context for %s", request["ticker"], exc_info=True)

        init_state = graph.propagator.create_initial_state(
            request["ticker"], request["analysis_date"],
            past_context=past_context,
            asset_type=config.get("asset_type", "stock"),
            crypto_interval=config.get("crypto_interval"),
            regime_context=request.get("regime_context", "") or "",
        )

        # For crypto: fetch live price + lower-timeframe candles so all agents
        # are aware of the current market price, not just historical klines.
        if config.get("asset_type") == "crypto" and hasattr(graph, "_crypto_shared"):
            import time as _time

            from tradingagents.dataflows.bybit_data import build_current_price_context
            as_of_ms = int(_time.time() * 1000)
            try:
                price_ctx = build_current_price_context(
                    request["ticker"],
                    **graph._crypto_shared,
                    as_of_ms=as_of_ms,
                    primary_interval=config.get("crypto_interval"),
                )
            except Exception as exc:
                logger.warning("Failed to fetch current price context: %s", exc)
                price_ctx = f"Current price data unavailable: {exc}"
            init_state["current_price_context"] = price_ctx

        args = graph.propagator.get_graph_args(callbacks=[callback])

        return {"early_result": None, "graph": graph, "init_state": init_state, "args": args}

    def _drive_stream_sync(self, run_id, graph, init_state, args, config, cancel_event):
        """Run the compiled graph via the SYNC stream and emit/persist per chunk.
        This is the existing, proven path (flag OFF) — behavior is unchanged."""
        last_chunk = None
        seq = make_seq_counter()
        parser_state = StreamParserState(
            workflow_mode=config.get("workflow_mode", "deep_analysis"),
            asset_type=config.get("asset_type", "stock"),
        )
        try:
            for chunk in graph.graph.stream(init_state, **args):
                if cancel_event.is_set():
                    break

                events = parse_stream_chunk(chunk, seq=seq, state=parser_state)
                for event in events:
                    self._bus.emit_threadsafe(run_id, event)
                    if isinstance(event, ReportChunkEvent) and event.section:
                        self._db.sync_save_report_section(run_id, event.section, event.content)

                last_chunk = chunk
        except GraphRecursionError:
            logger.warning(
                "Analysis %s hit recursion limit (%s) — returning partial results",
                run_id, config.get("max_recur_limit", 100),
            )
            self._bus.emit_threadsafe(run_id, ProgressEvent(
                phase="warning",
                detail=f"Recursion limit ({config.get('max_recur_limit', 100)}) reached — returning partial results",
            ))
        return last_chunk

    async def _aexecute_graph(
        self, run_id: str, request: Dict[str, Any], config: Dict[str, Any],
        callback: Any, cancel_event: threading.Event,
    ) -> Optional[Dict[str, Any]]:
        """ASYNC mirror of _execute_graph (flag ON). The SAME compiled graph and the SAME
        shared setup run, but the graph is driven via astream ON THE EVENT LOOP so the LLM
        calls inside the agent nodes are non-blocking and many symbols progress concurrently.
        The blocking setup (prefilter, memory log, Bybit price fetch) runs in a thread so it
        never stalls the loop. Output is identical to the sync path — same nodes, same order."""
        prep = await asyncio.to_thread(
            self._prepare_graph_run, run_id, request, config, callback
        )
        if prep.get("early_result") is not None:
            return prep["early_result"]
        graph, init_state, args = prep["graph"], prep["init_state"], prep["args"]
        last_chunk = await self._adrive_stream(run_id, graph, init_state, args, config, cancel_event)
        # _persist_signal_sections does sync DB writes — keep it off the loop.
        await asyncio.to_thread(self._persist_signal_sections, run_id, last_chunk)
        return last_chunk

    async def _adrive_stream(self, run_id, graph, init_state, args, config, cancel_event):
        """Async mirror of _drive_stream_sync: drive the graph via astream, emit on-loop
        (emit, not emit_threadsafe), and persist report sections via the async DB sink.
        Same chunk parsing, same events, same cancellation check as the sync path.

        KNOWN, INTENTIONAL DIFFERENCE (observability only, NOT trading output): chunk events
        here emit immediately on-loop, while the sync WebCallbackHandler runs in executor
        threads and routes its events through emit_threadsafe (deferred via
        call_soon_threadsafe). So the live agent-reasoning FEED and the snapshot `messages`
        list MAY be ordered slightly differently between flag-off and flag-on. The
        final_trade_decision and all report sections are UNAFFECTED — they come from chunk
        events and are persisted via keyed/idempotent upserts, so the golden-diff (which
        compares decision + structured signal + report sections) is unaffected."""
        last_chunk = None
        seq = make_seq_counter()
        parser_state = StreamParserState(
            workflow_mode=config.get("workflow_mode", "deep_analysis"),
            asset_type=config.get("asset_type", "stock"),
        )
        try:
            async for chunk in graph.graph.astream(init_state, **args):
                if cancel_event.is_set():
                    break

                events = parse_stream_chunk(chunk, seq=seq, state=parser_state)
                for event in events:
                    self._bus.emit(run_id, event)
                    if isinstance(event, ReportChunkEvent) and event.section:
                        await self._db.save_report_section(run_id, event.section, event.content)

                last_chunk = chunk
        except GraphRecursionError:
            logger.warning(
                "Analysis %s hit recursion limit (%s) — returning partial results",
                run_id, config.get("max_recur_limit", 100),
            )
            self._bus.emit(run_id, ProgressEvent(
                phase="warning",
                detail=f"Recursion limit ({config.get('max_recur_limit', 100)}) reached — returning partial results",
            ))
        return last_chunk

    async def _reclaim_zombie_async(self, run_id: str) -> None:
        async with self._lock:
            self._zombie_count = max(0, self._zombie_count - 1)
        logger.error("Hard zombie reclamation for run %s", run_id)


class ConcurrencyLimitError(Exception):
    """Raised when a new analysis is rejected due to concurrency/shutdown limits."""


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return "{}"
