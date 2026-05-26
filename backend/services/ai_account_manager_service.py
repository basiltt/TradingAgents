"""AI Account Manager Service — Phase 2 Task 2.3.

Orchestrates per-account AI manager tasks, health sweeps, and lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Optional

from backend.ai_manager_schemas import AIManagerConfig, AIManagerStatus
from backend.services.ai_manager_circuit_breaker import AIManagerCircuitBreaker
from backend.services.ai_manager_degradation import DegradationTierManager
from backend.services.ai_manager_llm_scheduler import PriorityLLMScheduler
from backend.services.ai_manager_repository import AIManagerRepository
from backend.services.position_lock_registry import PositionLockRegistry

if TYPE_CHECKING:
    from backend.services.ai_manager_task import AIManagerTask

logger = logging.getLogger(__name__)

MAX_DAILY_TOKEN_BUDGET = 100_000


class AIAccountManagerService:
    def __init__(
        self,
        accounts_service,
        close_positions_service,
        ws_manager,
        ai_manager_repo: AIManagerRepository,
        market_data_cache,
        position_lock_registry: PositionLockRegistry,
        llm_scheduler: PriorityLLMScheduler,
        hmac_key: str = "",
    ):
        self._accounts_service = accounts_service
        self._close_positions_service = close_positions_service
        self._ws_manager = ws_manager
        self._repo = ai_manager_repo
        self._market_data_cache = market_data_cache
        self._lock_registry = position_lock_registry
        self._llm_scheduler = llm_scheduler
        self._hmac_key = hmac_key
        self._tasks: Dict[str, "AIManagerTask"] = {}
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._compiled_graph = None
        self._health_task: Optional[asyncio.Task] = None
        self._dead_letter_task: Optional[asyncio.Task] = None
        self._pattern_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._singleton_conn = None
        self._circuit_breaker = AIManagerCircuitBreaker(repo=ai_manager_repo)
        self._degradation = DegradationTierManager(repo=ai_manager_repo)
        self._memory = None
        try:
            from backend.services.ai_manager_memory import AIManagerMemory
            self._memory = AIManagerMemory(repo=ai_manager_repo)
        except Exception:
            logger.warning("AIManagerMemory not available")

    async def start(self) -> None:
        """Compile LangGraph ONCE. Load enabled managers (stagger 5/s). Start health sweep."""
        if not self._hmac_key:
            raise RuntimeError("AI_MANAGER_HMAC_KEY is required but not set")

        # Single-worker assertion via advisory lock (held for service lifetime)
        if self._repo._pool:
            try:
                self._singleton_conn = await self._repo._pool.acquire()
                locked = await self._singleton_conn.fetchval(
                    "SELECT pg_try_advisory_lock(hashtext('ai_account_manager_singleton'))"
                )
                if not locked:
                    await self._repo._pool.release(self._singleton_conn)
                    self._singleton_conn = None
                    raise RuntimeError("Another AI Account Manager instance is already running")
            except RuntimeError:
                raise
            except Exception:
                logger.warning("Could not acquire advisory lock — skipping single-worker check")
                if self._singleton_conn:
                    await self._repo._pool.release(self._singleton_conn)
                    self._singleton_conn = None

        from backend.services.ai_manager_graph import build_decision_graph

        try:
            self._compiled_graph = build_decision_graph().compile()
            await self._degradation.load_from_db()
            await self._startup_reconciliation()
        except Exception:
            if self._singleton_conn:
                try:
                    await self._singleton_conn.execute(
                        "SELECT pg_advisory_unlock(hashtext('ai_account_manager_singleton'))"
                    )
                    await self._repo._pool.release(self._singleton_conn)
                except Exception:
                    pass
                self._singleton_conn = None
            raise

        # Start background loops
        self._health_task = asyncio.create_task(self._health_sweep_loop())
        self._dead_letter_task = asyncio.create_task(self._dead_letter_loop())
        self._pattern_task = asyncio.create_task(self._pattern_generation_loop())

        # Register global WS listener
        if self._ws_manager:
            self._ws_manager.register_wallet_listener(self._on_ws_event)

        logger.info("AIAccountManagerService started")

    async def shutdown(self) -> None:
        self._shutdown_event.set()

        # Deregister WS listener
        if self._ws_manager:
            self._ws_manager.deregister_wallet_listener(self._on_ws_event)

        # Cancel all per-account tasks
        for account_id, task in list(self._tasks.items()):
            task.cancel()

        # Wait with timeout
        if self._tasks:
            pending = [t._task for t in self._tasks.values() if hasattr(t, '_task') and t._task]
            if pending:
                await asyncio.wait(pending, timeout=5.0)

        # Cancel background tasks
        bg_tasks = [bg for bg in [self._health_task, self._dead_letter_task, self._pattern_task] if bg and not bg.done()]
        for bg in bg_tasks:
            bg.cancel()
        if bg_tasks:
            await asyncio.gather(*bg_tasks, return_exceptions=True)

        # Release singleton advisory lock connection
        if self._singleton_conn:
            try:
                await self._singleton_conn.execute(
                    "SELECT pg_advisory_unlock(hashtext('ai_account_manager_singleton'))"
                )
                await self._repo._pool.release(self._singleton_conn)
            except Exception:
                pass
            self._singleton_conn = None

        logger.info("AIAccountManagerService shutdown complete")

    async def _startup_reconciliation(self) -> None:
        """Load circuit breaker state, scan for stranded decisions."""
        rows = await self._repo.get_enabled_accounts()
        for row in rows:
            await self._circuit_breaker.load_from_db(
                row["account_id"],
                row["circuit_breaker_count"],
                row["circuit_breaker_active"],
            )

        # Scan for stranded decisions (crash recovery)
        stranded = await self._repo.get_stranded_decisions()
        for s in stranded:
            await self._repo.insert_failed_outcome(
                s["id"], s["timestamp"], {}, "crash_recovery"
            )
            await self._repo.update_decision_outcome(
                s["id"], s["timestamp"], {"status": "crash_recovery", "execution_result": {}}
            )
            logger.warning("Stranded decision %d recovered to dead-letter", s["id"])

        # Spawn tasks for enabled accounts (staggered)
        for i, row in enumerate(rows):
            await self._spawn_task(row["account_id"])
            if (i + 1) % 5 == 0:
                await asyncio.sleep(1.0)

    def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    async def enable(self, account_id: str, config: AIManagerConfig) -> None:
        lock = self._get_account_lock(account_id)
        async with lock:
            if account_id in self._tasks:
                return  # Already enabled (idempotent)
            await self._repo.upsert_state(account_id, enabled=True, fsm_state="sleeping")
            await self._repo.sync_config_columns(account_id, config.model_dump())
            await self._spawn_task(account_id)

    async def disable(self, account_id: str) -> None:
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.pop(account_id, None)
            if task:
                task.cancel()
            await self._repo.upsert_state(account_id, enabled=False, fsm_state="sleeping")
            await self._lock_registry.cleanup_account(account_id, force=True)
        self._account_locks.pop(account_id, None)

    async def pause(self, account_id: str, duration_hours: Optional[float] = None) -> None:
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.get(account_id)
            if task:
                task.pause()
            await self._repo.upsert_state(account_id, fsm_state="paused")

    async def resume(self, account_id: str) -> None:
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.get(account_id)
            if task:
                task.resume()
                await self._repo.upsert_state(account_id, fsm_state=task.state)
            else:
                await self._repo.upsert_state(account_id, fsm_state="sleeping")

    async def kill(self, account_id: str) -> None:
        await self._repo.set_kill_switch(account_id, True)
        task = self._tasks.get(account_id)
        if task:
            task.set_killed()

    async def global_kill(self) -> None:
        await self._repo.set_global_kill(True)
        for task in self._tasks.values():
            task.set_killed()

    async def update_config(self, account_id: str, config: AIManagerConfig) -> None:
        await self._repo.sync_config_columns(account_id, config.model_dump())
        task = self._tasks.get(account_id)
        if task:
            task.reload_config(config)

    async def get_status(self, account_id: str) -> Optional[AIManagerStatus]:
        state = await self._repo.get_state(account_id)
        if not state:
            return None
        return AIManagerStatus(
            enabled=state["enabled"],
            state=state["fsm_state"],
            last_analysis_at=state.get("last_analysis_at"),
            circuit_breaker={
                "count": state.get("circuit_breaker_count", 0),
                "active": state.get("circuit_breaker_active", False),
            },
            actions_today=state.get("actions_today", 0),
            budget_remaining={
                "actions": state.get("max_daily_actions", 30) - state.get("actions_today", 0),
                "tokens": MAX_DAILY_TOKEN_BUDGET - state.get("token_budget_used_today", 0),
            },
            degradation_tier=self._degradation.get_tier(),
            kill_switch=state.get("kill_switch_active", False),
        )

    async def reset_kill_switch(self, account_id: str) -> None:
        await self._repo.set_kill_switch(account_id, False)
        task = self._tasks.get(account_id)
        if task:
            task._killed = False

    async def patch_config(self, account_id: str, updates: dict) -> None:
        state = await self._repo.get_state(account_id)
        if not state:
            raise ValueError(f"Account {account_id} not configured")
        raw_config = state.get("config") or {}
        if isinstance(raw_config, str):
            import json as _json
            raw_config = _json.loads(raw_config)
        raw_config.update(updates)
        config = AIManagerConfig(**raw_config)
        await self._repo.sync_config_columns(account_id, config.model_dump())
        task = self._tasks.get(account_id)
        if task:
            task.reload_config(config)

    async def lock_position(self, account_id: str, symbol: str) -> None:
        state = await self._repo.get_state(account_id)
        if not state:
            raise ValueError(f"Account {account_id} not configured")
        raw_config = state.get("config") or {}
        if isinstance(raw_config, str):
            import json as _json
            raw_config = _json.loads(raw_config)
        locked = set(raw_config.get("locked_positions", []))
        locked.add(symbol)
        raw_config["locked_positions"] = sorted(locked)
        config = AIManagerConfig(**raw_config)
        await self._repo.sync_config_columns(account_id, config.model_dump())
        task = self._tasks.get(account_id)
        if task:
            task.reload_config(config)

    async def unlock_position(self, account_id: str, symbol: str) -> None:
        state = await self._repo.get_state(account_id)
        if not state:
            raise ValueError(f"Account {account_id} not configured")
        raw_config = state.get("config") or {}
        if isinstance(raw_config, str):
            import json as _json
            raw_config = _json.loads(raw_config)
        locked = set(raw_config.get("locked_positions", []))
        locked.discard(symbol)
        raw_config["locked_positions"] = sorted(locked)
        config = AIManagerConfig(**raw_config)
        await self._repo.sync_config_columns(account_id, config.model_dump())
        task = self._tasks.get(account_id)
        if task:
            task.reload_config(config)

    async def get_decisions(
        self, account_id: str, limit: int = 50, cursor: Optional[str] = None, outcome_filter: Optional[str] = None
    ) -> dict:
        from datetime import datetime, timezone
        cursor_ts = None
        cursor_id = None
        if cursor:
            try:
                parts = cursor.split("_", 1)
                if len(parts) == 2:
                    cursor_ts = datetime.fromisoformat(parts[0])
                    cursor_id = int(parts[1])
            except (ValueError, TypeError):
                pass
        items, next_cursor = await self._repo.get_decisions_page(
            account_id, cursor_ts=cursor_ts, cursor_id=cursor_id,
            limit=limit, outcome_filter=outcome_filter,
        )
        return {"decisions": items, "next_cursor": next_cursor}

    async def get_performance(self, account_id: str, period: str = "7d") -> dict:
        return await self._repo.get_performance_metrics(account_id, period=period)

    async def _spawn_task(self, account_id: str) -> None:
        from backend.services.ai_manager_task import AIManagerTask

        state = await self._repo.get_state(account_id)
        if not state or not state.get("enabled", False):
            return
        try:
            raw_config = state.get("config") or {}
            if isinstance(raw_config, str):
                import json as _json
                raw_config = _json.loads(raw_config)
            config = AIManagerConfig(**raw_config)
        except Exception:
            logger.warning("Invalid config for %s, using defaults", account_id)
            config = AIManagerConfig()

        task = AIManagerTask(
            account_id=account_id,
            service=self,
            config=config,
            compiled_graph=self._compiled_graph,
        )
        self._tasks[account_id] = task
        task.start()

    async def _on_ws_event(self, account_id: str, wallet_data: dict) -> None:
        task = self._tasks.get(account_id)
        if task:
            await task.on_ws_event(wallet_data)

    async def emit_event(self, account_id: str, event_type: str, payload: dict) -> None:
        if self._ws_manager:
            try:
                await self._ws_manager.broadcast_to_account(
                    account_id, f"ai_manager.{event_type}", payload
                )
            except Exception:
                logger.debug("Failed to emit ai_manager.%s for %s", event_type, account_id)

    async def _health_sweep_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(30.0)
                await self._lock_registry.evict_stale()
                # Check for dead tasks
                for account_id, task in list(self._tasks.items()):
                    if task.is_dead():
                        if self._shutdown_event.is_set():
                            break
                        lock = self._get_account_lock(account_id)
                        async with lock:
                            if account_id in self._tasks and self._tasks[account_id].is_dead():
                                logger.warning("Dead task detected: %s, restarting", account_id)
                                self._tasks.pop(account_id, None)
                                await self._spawn_task(account_id)
                # Heartbeat-orphan detection (stalled tasks still alive as asyncio tasks)
                for account_id, task in list(self._tasks.items()):
                    if not task.is_dead() and task._heartbeat_at > 0:
                        import time as _time
                        elapsed = _time.monotonic() - task._heartbeat_at
                        if elapsed > 180.0 and task._state not in ("sleeping", "paused", "monitoring"):
                            lock = self._get_account_lock(account_id)
                            async with lock:
                                t = self._tasks.get(account_id)
                                if t and not t.is_dead() and t._heartbeat_at > 0:
                                    re_elapsed = _time.monotonic() - t._heartbeat_at
                                    if re_elapsed > 180.0 and t._state not in ("sleeping", "paused", "monitoring"):
                                        logger.warning("Stalled task detected: %s (%.0fs), restarting", account_id, re_elapsed)
                                        t.cancel()
                                        self._tasks.pop(account_id, None)
                                        await self._lock_registry.cleanup_account(account_id)
                                        await self._spawn_task(account_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Health sweep error")

    async def _dead_letter_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(60.0)
                pending = await self._repo.get_pending_retries(limit=10)
                for item in pending:
                    if item["retry_count"] >= item["max_retries"]:
                        await self._repo.update_decision_outcome(
                            item["decision_id"],
                            item["decision_timestamp"],
                            {"status": "dead_letter_exhausted", "execution_result": {}},
                        )
                        await self._repo.mark_resolved(item["id"], "max_retries_exhausted")
                        logger.error("Dead-letter exhausted: id=%d", item["id"])
                    else:
                        await self._repo.increment_retry(item["id"])
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Dead-letter loop error")

    async def _pattern_generation_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(86400.0)  # 24h
                if self._shutdown_event.is_set():
                    break
                rows = await self._repo.get_enabled_accounts()
                for i, row in enumerate(rows):
                    if self._shutdown_event.is_set():
                        break
                    account_id = row["account_id"]
                    if hasattr(self, '_memory') and self._memory:
                        try:
                            await self._memory.generate_patterns(account_id)
                        except Exception:
                            logger.warning("Pattern generation failed for %s", account_id)
                    # Stagger: 1 account per 2 seconds
                    if (i + 1) % 1 == 0:
                        await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Pattern generation loop error")

    @classmethod
    def create(cls, app_state) -> "AIAccountManagerService":
        import os

        return cls(
            accounts_service=app_state.get("accounts_service"),
            close_positions_service=app_state.get("close_positions_service"),
            ws_manager=app_state.get("account_ws_manager"),
            ai_manager_repo=AIManagerRepository(app_state.get("db_pool")),
            market_data_cache=app_state.get("market_data_cache"),
            position_lock_registry=app_state.get("position_lock_registry", PositionLockRegistry()),
            llm_scheduler=app_state.get("llm_scheduler", PriorityLLMScheduler()),
            hmac_key=os.environ.get("AI_MANAGER_HMAC_KEY", ""),
        )
