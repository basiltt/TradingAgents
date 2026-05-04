"""Analysis service — manages analysis lifecycle with concurrency control — TASK-012."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import uuid
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.utils import mask_secrets
from backend.callbacks import WebCallbackHandler
from backend.event_bus import EventBus
from backend.persistence import AnalysisDB
from backend.services.config_service import ConfigService
from backend.stream_parser import parse_stream_chunk, make_seq_counter, StreamParserState, AgentStatusEvent, ProgressEvent
from backend.validators import validate_backend_url
from backend.ws_manager import WSManager

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 10
_MAX_ZOMBIES = 3
_WALL_TIMEOUT = 30 * 60  # 30 minutes
_HARD_TIMEOUT = 35 * 60  # 35 minutes


class AnalysisService:
    def __init__(
        self,
        persistence: AnalysisDB,
        event_bus: EventBus,
        ws_manager: WSManager,
        config_service: ConfigService,
    ):
        self._db = persistence
        self._bus = event_bus
        self._ws = ws_manager
        self._config = config_service
        self._active_runs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._zombie_count = 0

    async def start_analysis(self, request: Dict[str, Any]) -> str:
        async with self._lock:
            active = sum(1 for r in self._active_runs.values() if r["status"] == "running")
            if active >= _MAX_CONCURRENT:
                raise ConcurrencyLimitError(
                    f"Maximum {_MAX_CONCURRENT} concurrent analyses. "
                    f"Please wait for a running analysis to complete."
                )
            if self._zombie_count >= _MAX_ZOMBIES:
                raise ConcurrencyLimitError("Too many zombie threads. Please wait.")

            run_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            config_snapshot = self._build_config(request)
            safe_config = mask_secrets(config_snapshot)

            await asyncio.to_thread(self._db.insert_run, {
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

        task = asyncio.create_task(self._run_analysis(run_id, request, config_snapshot))
        async with self._lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["task"] = task

        return run_id

    async def cancel_analysis(self, run_id: str) -> bool:
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

        db_run = await asyncio.to_thread(self._db.get_run, run_id)
        if not db_run:
            return False
        return db_run["status"] != "running"

    async def shutdown(self) -> None:
        tasks_to_await = []
        async with self._lock:
            for rid, run in list(self._active_runs.items()):
                if run.get("cancel_event"):
                    run["cancel_event"].set()
                task = run.get("task")
                if task and not task.done():
                    task.cancel()
                    tasks_to_await.append(task)
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._db.get_run, run_id)

    async def delete_run(self, run_id: str) -> bool:
        return await asyncio.to_thread(self._db.delete_run, run_id)

    async def delete_all_runs(self) -> int:
        return await asyncio.to_thread(self._db.delete_all_runs)

    async def list_runs(self, **kwargs) -> Dict[str, Any]:
        return await asyncio.to_thread(self._db.list_runs, **kwargs)

    async def get_report(self, run_id: str) -> Optional[str]:
        sections = await asyncio.to_thread(self._db.get_report_sections, run_id)
        if not sections:
            return None
        return "\n\n---\n\n".join(s["content"] for s in sections if s["section"] != "_snapshot")

    async def get_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        sections = await asyncio.to_thread(self._db.get_report_sections, run_id)
        snapshot = None
        for s in sections:
            if s["section"] == "_snapshot":
                try:
                    snapshot = json.loads(s["content"])
                except (json.JSONDecodeError, TypeError):
                    pass
                break
        if snapshot is None:
            return None
        # Backfill reports from individually saved DB sections if snapshot reports are empty
        if not snapshot.get("reports"):
            reports = {s["section"]: s["content"] for s in sections if s["section"] != "_snapshot"}
            if reports:
                snapshot["reports"] = reports
        return snapshot

    def _build_config(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from tradingagents.default_config import DEFAULT_CONFIG

        config = copy.deepcopy(DEFAULT_CONFIG)

        resolved = self._config.get_config()["resolved"]
        for k, v in resolved.items():
            if v != "***":
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
            config["data_vendors"].update(request["data_vendors"])
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

        # Crypto-specific config
        if request.get("asset_type"):
            config["asset_type"] = request["asset_type"]
        if request.get("interval"):
            config["crypto_interval"] = request["interval"]

        backend_url = request.get("backend_url") or os.getenv("TRADINGAGENTS_BACKEND_URL")
        if backend_url:
            config["backend_url"] = validate_backend_url(backend_url, server_port=8000)

        return config

    async def _run_analysis(
        self, run_id: str, request: Dict[str, Any], config: Dict[str, Any]
    ) -> None:
        async with self._lock:
            cancel_event = self._active_runs.get(run_id, {}).get("cancel_event", threading.Event())

        try:
            self._bus.emit(run_id, ProgressEvent(phase="starting", detail="Initializing analysis"))

            callback = WebCallbackHandler(run_id=run_id, event_bus=self._bus)

            result = await asyncio.wait_for(
                asyncio.to_thread(self._execute_graph, run_id, request, config, callback, cancel_event),
                timeout=_WALL_TIMEOUT,
            )

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            updated = await asyncio.to_thread(self._db.update_run_status, run_id, "completed", None, now)

            if updated and isinstance(result, dict):
                decision = result.get("final_trade_decision", "")
                if decision:
                    await asyncio.to_thread(self._db.save_report_section, run_id, "final_trade_decision", str(decision))

            if updated:
                self._bus.emit(run_id, ProgressEvent(phase="completed", detail="Analysis complete"))

        except asyncio.CancelledError:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            self._db.update_run_status(run_id, "cancelled", "Cancelled by user", now)
            self._bus.emit(run_id, ProgressEvent(phase="cancelled", detail="Cancelled"))

        except asyncio.TimeoutError:
            cancel_event.set()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            self._db.update_run_status(run_id, "failed", "Wall-clock timeout (30min)", now)
            self._bus.emit(run_id, ProgressEvent(phase="failed", detail="Timeout"))
            async with self._lock:
                self._zombie_count += 1
            asyncio.get_running_loop().call_later(
                _HARD_TIMEOUT - _WALL_TIMEOUT,
                lambda rid=run_id: asyncio.create_task(self._reclaim_zombie_async(rid)),
            )

        except Exception as e:
            logger.error("Analysis %s failed: %s", run_id, e, exc_info=True)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            self._db.update_run_status(run_id, "failed", "Internal error occurred", now)
            self._bus.emit(run_id, ProgressEvent(phase="failed", detail="An error occurred"))

        finally:
            # Let pending emit_threadsafe coroutines execute before reading ring buffer
            await asyncio.sleep(0.2)
            self._save_snapshot(run_id)
            async with self._lock:
                run_data = self._active_runs.pop(run_id, None)
                if run_data:
                    run_data["status"] = "terminal"

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
            self._db.save_report_section(run_id, "_snapshot", json.dumps(snapshot, default=str))
            for section, content in reports.items():
                self._db.save_report_section(run_id, section, content)
        except Exception:
            logger.warning("Failed to save snapshot for run %s", run_id, exc_info=True)

    def _persist_signal_sections(self, run_id: str, last_chunk) -> None:
        """Save _pm_signal and _trader_signal JSON sections from the final graph chunk.

        Called from _execute_graph (runs in a thread), so sync DB calls are safe here.
        """
        if not last_chunk:
            return
        import json as _json_local
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
                    json_str = _json_local.dumps(obj)
                else:
                    continue
                self._db.save_report_section(run_id, section_name, json_str)
            except Exception:
                logger.warning(
                    "Failed to persist %s for run %s", section_name, run_id, exc_info=True
                )

    def _execute_graph(
        self, run_id: str, request: Dict[str, Any], config: Dict[str, Any],
        callback: Any, cancel_event: threading.Event,
    ) -> Optional[Dict[str, Any]]:
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError:
            logger.warning("TradingAgentsGraph not available, using mock")
            return {"final_trade_decision": "Mock decision — TradingAgentsGraph not installed"}

        graph = TradingAgentsGraph(
            config=config,
            selected_analysts=[a.value if hasattr(a, "value") else a for a in (request.get("analysts") or (
                ["crypto_technical", "crypto_derivatives", "crypto_news"]
                if config.get("asset_type") == "crypto"
                else ["market", "news"]
            ))],
        )

        init_state = graph.propagator.create_initial_state(
            request["ticker"], request["analysis_date"],
            asset_type=config.get("asset_type", "stock"),
        )
        args = graph.propagator.get_graph_args(callbacks=[callback])

        last_chunk = None
        seq = make_seq_counter()
        parser_state = StreamParserState()
        for chunk in graph.graph.stream(init_state, **args):
            if cancel_event.is_set():
                break

            events = parse_stream_chunk(chunk, seq=seq, state=parser_state)
            for event in events:
                self._bus.emit_threadsafe(run_id, event)
                if hasattr(event, "type") and event.type == "report_chunk" and event.section:
                    self._db.save_report_section(run_id, event.section, event.content)

            last_chunk = chunk

        self._persist_signal_sections(run_id, last_chunk)
        return last_chunk

    async def _reclaim_zombie_async(self, run_id: str) -> None:
        async with self._lock:
            self._zombie_count = max(0, self._zombie_count - 1)
        logger.error("Hard zombie reclamation for run %s", run_id)


class ConcurrencyLimitError(Exception):
    pass


def _safe_json(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return "{}"
