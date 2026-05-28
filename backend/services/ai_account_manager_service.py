"""AI Account Manager Service — Phase 2 Task 2.3.

Orchestrates per-account AI manager tasks, health sweeps, and lifecycle management.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import time as _time
from datetime import datetime, timedelta, timezone
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

MAX_DAILY_TOKEN_BUDGET = 20_000_000


class AIAccountManagerService:
    """Top-level orchestrator for AI-managed trading accounts.

    Manages per-account AIManagerTask instances, enforces singleton operation via
    PostgreSQL advisory lock, runs background health sweeps (detect dead tasks),
    dead-letter retry loops, and periodic pattern generation via LLM.

    Dependencies injected at construction; _llm_callable and _pattern_llm_callable
    must be assigned externally before start() for LLM features to function.
    """

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
        self._reconcile_lock = asyncio.Lock()
        self._compiled_graph = None
        self._health_task: Optional[asyncio.Task] = None
        self._dead_letter_task: Optional[asyncio.Task] = None
        self._pattern_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._singleton_conn = None
        self._circuit_breaker = AIManagerCircuitBreaker(repo=ai_manager_repo)
        self._degradation = DegradationTierManager(repo=ai_manager_repo)
        self._llm_callable = None  # Set externally: async (system_prompt, context_prompt) -> str
        self._pattern_llm_callable = None  # Set externally when LLM provider is configured
        self._memory = None
        self._llm_logger = None  # Initialized in start()
        try:
            from backend.services.ai_manager_memory import AIManagerMemory
            self._memory = AIManagerMemory(repo=ai_manager_repo)
        except Exception:
            logger.warning("AIManagerMemory not available")

    async def start(self) -> None:
        """Compile LangGraph ONCE. Load enabled managers (stagger 5/s). Start health sweep."""
        if not self._hmac_key:
            logger.warning("AI_MANAGER_HMAC_KEY not set — AI Manager disabled (set env var to enable)")
            return

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

        # Start LLM call logger
        from backend.services.ai_manager_llm_logger import LLMCallBatchLogger
        self._llm_logger = LLMCallBatchLogger(repo=self._repo)
        await self._llm_logger.start()

        # Register global WS listener
        if self._ws_manager:
            self._ws_manager.register_wallet_listener(self._on_ws_event)

        logger.info("AIAccountManagerService started")

        try:
            await self.reconcile_active_schedules()
        except Exception:
            logger.exception("AI Manager: failed to reconcile active schedules on startup")

    async def shutdown(self) -> None:
        """Gracefully stop all tasks, background loops, and release the advisory lock."""
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

        # Stop LLM logger (flush remaining buffer)
        if self._llm_logger:
            await self._llm_logger.stop()

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
        logger.info(
            "AI Manager startup: %d enabled account(s) found",
            len(rows),
        )
        for i, row in enumerate(rows):
            logger.info(
                "AI Manager: spawning task for account %s (cb_count=%d, cb_active=%s)",
                row["account_id"],
                row.get("circuit_breaker_count", 0),
                row.get("circuit_breaker_active", False),
            )
            await self._spawn_task(row["account_id"])
            if (i + 1) % 5 == 0:
                await asyncio.sleep(1.0)

        logger.info(
            "AI Manager startup complete: %d task(s) running",
            len(self._tasks),
        )

    def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    async def enable(self, account_id: str, config: AIManagerConfig) -> None:
        """Enable AI Manager for an account — spawns the decision loop task."""
        lock = self._get_account_lock(account_id)
        async with lock:
            existing_task = self._tasks.get(account_id)
            if existing_task and not existing_task.is_dead():
                # Task is alive — just sync config if it changed
                if getattr(existing_task._config, "auto_enabled", False) != config.auto_enabled:
                    await self._repo.sync_config_columns(account_id, config.model_dump())
                    existing_task.reload_config(config)
                return
            # No task or dead task — (re)spawn
            if existing_task and existing_task.is_dead():
                logger.info("AI Manager: respawning dead task for account %s on enable()", account_id)
                self._tasks.pop(account_id, None)
            await self._repo.upsert_state(account_id, enabled=True, fsm_state="sleeping")
            await self._repo.sync_config_columns(account_id, config.model_dump())
            await self._spawn_task(account_id)
            source = "auto" if config.auto_enabled else "manual"
            await self._repo.insert_log(account_id, "info", "lifecycle", f"AI Manager enabled ({source})")

    async def disable(self, account_id: str) -> None:
        """Disable AI Manager — cancels the task and clears state."""
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.pop(account_id, None)
            if task:
                task.cancel()
            await self._repo.upsert_state(
                account_id, enabled=False, fsm_state="sleeping",
                emergency_ref_equity=None, emergency_cooldown_until=None,
                emergency_closed_symbols="{}",
            )
            await self._lock_registry.cleanup_account(account_id, force=True)
            await self._repo.insert_log(account_id, "info", "lifecycle", "AI Manager disabled")
        self._account_locks.pop(account_id, None)

    async def pause(self, account_id: str, duration_hours: Optional[float] = None) -> None:
        """Pause the decision loop; positions remain open but unmanaged."""
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.get(account_id)
            if task:
                task.pause()
            else:
                # No task running — persist directly
                await self._repo.upsert_state(account_id, fsm_state="paused")

    async def resume(self, account_id: str) -> None:
        """Resume a paused decision loop."""
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.get(account_id)
            if task:
                task.resume()
            else:
                await self._repo.upsert_state(account_id, fsm_state="sleeping")

    async def kill(self, account_id: str) -> None:
        """Activate per-account kill switch — halts all AI decisions."""
        await self._repo.set_kill_switch(account_id, True)
        task = self._tasks.get(account_id)
        if task:
            task.set_killed()

    async def global_kill(self) -> None:
        """Activate global kill switch — halts ALL AI decisions across all accounts."""
        await self._repo.set_global_kill(True)
        for task in self._tasks.values():
            task.set_killed()

    async def update_config(self, account_id: str, config: AIManagerConfig) -> None:
        """Persist new config and hot-reload into the running task."""
        lock = self._get_account_lock(account_id)
        async with lock:
            await self._repo.sync_config_columns(account_id, config.model_dump())
            task = self._tasks.get(account_id)
            if task:
                task.reload_config(config)

    def get_all_task_states(self) -> Dict[str, str]:
        """Return {account_id: state} for all active (non-dead) AI manager tasks."""
        return {aid: t.state for aid, t in self._tasks.items() if not t.is_dead()}

    def get_task(self, account_id: str) -> Optional["AIManagerTask"]:
        """Return the in-memory task for an account, or None if not running."""
        task = self._tasks.get(account_id)
        if task and not task.is_dead():
            return task
        return None

    async def get_status(self, account_id: str) -> Optional[AIManagerStatus]:
        """Build full status object including real-time FSM state from in-memory task."""
        state = await self._repo.get_state(account_id)
        if not state:
            return None
        
        # Resolve real-time FSM state from in-memory task if active
        fsm_state = state["fsm_state"]
        task = self._tasks.get(account_id)
        
        emergency_ref_equity = state.get("emergency_ref_equity")
        emergency_cooldown_until = state.get("emergency_cooldown_until")
        raw_closed_symbols = state.get("emergency_closed_symbols")
        
        if task and not task.is_dead():
            fsm_state = task.state
            now_mono = _time.monotonic()
            now_utc = datetime.now(timezone.utc)
            
            # Get real-time ref equity
            ws_buf = getattr(task, "_ws_buffer", None)
            if isinstance(ws_buf, dict):
                emergency_ref_equity = ws_buf.get("_emergency_ref_equity")
            
            # Get real-time cooldown
            cooldown_val = getattr(task, "_emergency_cooldown_until", None)
            if isinstance(cooldown_val, (int, float)):
                remaining = cooldown_val - now_mono
                if remaining > 0:
                    emergency_cooldown_until = now_utc + timedelta(seconds=remaining)
                else:
                    emergency_cooldown_until = None
            else:
                emergency_cooldown_until = None
                
            # Get real-time closed symbols
            closed_syms = getattr(task, "_emergency_closed_symbols", None)
            if isinstance(closed_syms, dict):
                symbols_json = {}
                for sym, mono_ts in closed_syms.items():
                    if isinstance(mono_ts, (int, float)):
                        age = now_mono - mono_ts
                        if age < 30.0:
                            symbols_json[sym] = (now_utc - timedelta(seconds=age)).isoformat()
                raw_closed_symbols = symbols_json

        # Parse closed symbols
        if isinstance(raw_closed_symbols, str):
            try:
                emergency_closed_symbols = _json.loads(raw_closed_symbols)
            except Exception:
                emergency_closed_symbols = {}
        elif isinstance(raw_closed_symbols, dict):
            emergency_closed_symbols = raw_closed_symbols
        else:
            emergency_closed_symbols = {}

        # --- Build runtime telemetry ---
        # Daily P&L
        equity_at_start = state.get("equity_at_day_start")
        realized_profit = float(state.get("realized_profit_today", 0) or 0)
        realized_loss = float(state.get("realized_loss_today", 0) or 0)
        net_daily = realized_profit - realized_loss
        # Config values from JSONB
        raw_config = state.get("config") or {}
        if isinstance(raw_config, str):
            raw_config = _json.loads(raw_config)
        max_daily_loss_pct = float(raw_config.get("max_daily_loss_pct") or 5.0)
        daily_profit_target_pct = raw_config.get("daily_profit_target_pct")

        daily_pnl_data = {
            "equity_at_start": float(equity_at_start) if equity_at_start else None,
            "realized_profit": realized_profit,
            "realized_loss": realized_loss,
            "net_pnl": net_daily,
            "loss_pct_used": None,
            "profit_target_progress": None,
        }
        if equity_at_start and float(equity_at_start) > 0:
            daily_pnl_data["loss_pct_used"] = round(
                (realized_loss / float(equity_at_start)) * 100 / max_daily_loss_pct * 100, 1
            )
            if daily_profit_target_pct and float(daily_profit_target_pct) > 0:
                target_val = float(daily_profit_target_pct) * float(equity_at_start) / 100
                daily_pnl_data["profit_target_progress"] = round(
                    min(realized_profit / target_val * 100, 100), 1
                ) if target_val > 0 else None

        # Token budget
        token_used = int(state.get("token_budget_used_today", 0) or 0)
        token_budget_data = {
            "used": token_used,
            "max": MAX_DAILY_TOKEN_BUDGET,
            "pct": round(token_used / MAX_DAILY_TOKEN_BUDGET * 100, 1),
        }

        # Live positions & current equity from in-memory WS buffer
        live_positions = None
        current_equity = None
        if task and not task.is_dead():
            ws_buf = getattr(task, "_ws_buffer", None)
            if isinstance(ws_buf, dict):
                eq = ws_buf.get("equity")
                if eq is not None:
                    try:
                        current_equity = float(eq)
                    except (ValueError, TypeError):
                        pass

                positions = ws_buf.get("positions") or []
                peak_pnl = ws_buf.get("_peak_pnl") or {}
                now_ms = _time.time() * 1000
                live_positions = []
                for pos in positions:
                    symbol = pos.get("symbol", "")
                    if not symbol:
                        continue
                    upnl_raw = pos.get("unrealisedPnl", pos.get("unrealized_pnl", 0))
                    try:
                        upnl = float(upnl_raw)
                    except (ValueError, TypeError):
                        upnl = 0.0
                    peak_val = peak_pnl.get(symbol, upnl)
                    drawdown = peak_val - upnl if peak_val > upnl else 0.0
                    # Position age
                    created_ms = pos.get("createdTime")
                    age_s = None
                    if created_ms:
                        try:
                            age_s = int((now_ms - int(created_ms)) / 1000)
                        except (ValueError, TypeError):
                            pass
                    live_positions.append({
                        "symbol": symbol,
                        "side": pos.get("side", ""),
                        "size": pos.get("size", "0"),
                        "entry_price": pos.get("avgPrice", pos.get("entryPrice", "")),
                        "current_upnl": round(upnl, 4),
                        "peak_pnl": round(float(peak_val), 4) if peak_val is not None else 0.0,
                        "drawdown_from_peak": round(drawdown, 4),
                        "age_s": age_s,
                    })

        return AIManagerStatus(
            enabled=state["enabled"],
            state=fsm_state,
            last_analysis_at=state.get("last_analysis_at"),
            circuit_breaker={
                "count": state.get("circuit_breaker_count", 0),
                "active": state.get("circuit_breaker_active", False),
            },
            actions_today=state.get("actions_today", 0),
            budget_remaining={
                "actions": max(0, state.get("max_daily_actions", 30) - state.get("actions_today", 0)),
                "tokens": max(0, MAX_DAILY_TOKEN_BUDGET - token_used),
            },
            degradation_tier=self._degradation.get_tier(),
            kill_switch=state.get("kill_switch_active", False),
            emergency_ref_equity=emergency_ref_equity,
            emergency_cooldown_until=emergency_cooldown_until,
            emergency_closed_symbols=emergency_closed_symbols,
            daily_pnl=daily_pnl_data,
            token_budget=token_budget_data,
            live_positions=live_positions,
            current_equity=current_equity,
        )

    async def reset_kill_switch(self, account_id: str) -> None:
        """Clear kill switch and respawn the task if it was terminated."""
        await self._repo.set_kill_switch(account_id, False)
        lock = self._get_account_lock(account_id)
        async with lock:
            task = self._tasks.get(account_id)
            if task:
                task._killed = False
                # If the underlying asyncio task was cancelled by set_killed(), respawn immediately
                if task.is_dead():
                    logger.info("AI Manager: respawning dead task for account %s after kill switch reset", account_id)
                    self._tasks.pop(account_id, None)
                    await self._spawn_task(account_id)
            else:
                # No task at all — spawn one (DB row is enabled since set_kill_switch doesn't set enabled=False)
                await self._spawn_task(account_id)

    async def get_config(self, account_id: str) -> dict:
        """Return the persisted AI Manager configuration as a dict."""
        state = await self._repo.get_state(account_id)
        if not state:
            raise ValueError(f"Account {account_id} not configured")
        raw_config = state.get("config") or {}
        if isinstance(raw_config, str):
            import json as _json
            raw_config = _json.loads(raw_config)
        config = AIManagerConfig(**raw_config)
        return config.model_dump()

    async def patch_config(self, account_id: str, updates: dict) -> None:
        """Merge partial config updates and hot-reload into the running task."""
        lock = self._get_account_lock(account_id)
        async with lock:
            state = await self._repo.get_state(account_id)
            if not state:
                raise ValueError(f"Account {account_id} not configured")
            raw_config = state.get("config") or {}
            if isinstance(raw_config, str):
                import json as _json
                raw_config = _json.loads(raw_config)
            # Null values mean "reset to default" — remove from config so AIManagerConfig defaults apply
            for key, val in updates.items():
                if val is None:
                    raw_config.pop(key, None)
                else:
                    raw_config[key] = val
            config = AIManagerConfig(**raw_config)
            await self._repo.sync_config_columns(account_id, config.model_dump())
            task = self._tasks.get(account_id)
            if task:
                task.reload_config(config)

    async def lock_position(self, account_id: str, symbol: str) -> None:
        """Add symbol to locked_positions — prevents AI from closing it."""
        lock = self._get_account_lock(account_id)
        async with lock:
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
        """Remove symbol from locked_positions — allows AI to manage it again."""
        lock = self._get_account_lock(account_id)
        async with lock:
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
        """Return paginated AI decisions with optional outcome filtering."""
        from datetime import datetime
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
        """Return aggregated performance metrics for the given time period."""
        return await self._repo.get_performance_metrics(account_id, period=period)

    async def get_logs(
        self, account_id: str, limit: int = 100,
        level: str | None = None, category: str | None = None,
        cursor_id: int | None = None,
    ) -> dict:
        """Return paginated AI Manager operational logs."""
        return await self._repo.get_logs(
            account_id, limit=limit,
            level_filter=level, category_filter=category,
            cursor_id=cursor_id,
        )

    async def write_log(
        self, account_id: str, level: str, category: str, message: str,
        details: dict | None = None,
    ) -> None:
        """Persist an operational log entry for the given account."""
        await self._repo.insert_log(account_id, level, category, message, details)

    async def reconcile_active_schedules(self) -> None:
        """Query active schedules and enable AI manager for accounts that have ai_manager_enabled=True."""
        if not self._repo._pool:
            return
        async with self._reconcile_lock:
            try:
                # Query all active, paused, or errored scheduled scans
                async with self._repo._pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT scan_config FROM scheduled_scans WHERE status IN ('active', 'paused', 'error')"
                    )
                
                enabled_accounts_in_schedules = set()
                for row in rows:
                    try:
                        scan_config = row["scan_config"]
                        if isinstance(scan_config, str):
                            scan_config = _json.loads(scan_config)
                        
                        auto_configs = scan_config.get("auto_trade_configs") or []
                        for cfg in auto_configs:
                            account_id = cfg.get("account_id")
                            if account_id and cfg.get("ai_manager_enabled"):
                                enabled_accounts_in_schedules.add(account_id)
                    except Exception:
                        logger.warning("Failed to parse scan_config in scheduled_scans reconciliation", exc_info=True)
                
                # 1. Enable and spawn tasks for accounts enabled in schedules
                for account_id in enabled_accounts_in_schedules:
                    existing_task = self._tasks.get(account_id)
                    # Skip if there's already a healthy running task
                    if existing_task and not existing_task.is_dead():
                        continue
                    config = None
                    try:
                        existing_config = await self.get_config(account_id)
                        from backend.ai_manager_schemas import AIManagerConfig as _AIMConfig
                        config = _AIMConfig(**existing_config)
                    except Exception:
                        pass
                    if not config:
                        from backend.ai_manager_schemas import AIManagerConfig as _AIMConfig
                        config = _AIMConfig()
                    
                    config.auto_enabled = True
                    logger.info("Auto-starting AI manager for account %s due to scheduled scan setting", account_id)
                    await self.enable(account_id, config)

                # 2. Disable tasks for accounts that were auto-started but are no longer in any active schedules.
                # Only consider accounts currently running in memory to avoid touching manually-enabled accounts
                # that may not have spawned tasks yet (e.g. still in DB-only state from a prior restart).
                for account_id in list(self._tasks.keys()):
                    if account_id not in enabled_accounts_in_schedules:
                        config = None
                        try:
                            existing_config = await self.get_config(account_id)
                            from backend.ai_manager_schemas import AIManagerConfig as _AIMConfig
                            config = _AIMConfig(**existing_config)
                        except Exception:
                            pass
                        
                        # Only auto-disable accounts that were auto-started (not manually enabled by user)
                        if config and config.auto_enabled:
                            logger.info(
                                "Auto-disabling AI manager for account %s (auto-started but no longer in active schedules)",
                                account_id,
                            )
                            await self.disable(account_id)

            except Exception:
                logger.exception("Error during scheduled scans AI manager reconciliation")

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

        # Load circuit breaker state from DB
        await self._circuit_breaker.load_from_db(
            account_id,
            state.get("circuit_breaker_count", 0),
            state.get("circuit_breaker_active", False),
        )

        # Fetch account label for per-account logging
        account_label = ""
        try:
            acct = await self._accounts_service.get_account(account_id)
            if acct:
                account_label = acct.get("label", "")
        except Exception:
            pass

        task = AIManagerTask(
            account_id=account_id,
            service=self,
            config=config,
            compiled_graph=self._compiled_graph,
            account_label=account_label,
        )
        task._restore_emergency_state(state)
        self._tasks[account_id] = task
        task.start()

    async def _on_ws_event(self, account_id: str, event: dict) -> None:
        task = self._tasks.get(account_id)
        if task:
            await task.on_ws_event(event)

    async def emit_event(self, account_id: str, event_type: str, payload: dict) -> None:
        """Broadcast an AI Manager event to connected frontend WebSocket clients."""
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
                                        await self._lock_registry.cleanup_account(account_id, force=True)
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
                            await self._memory.generate_patterns(
                                account_id, llm_callable=self._pattern_llm_callable
                            )
                        except Exception:
                            logger.warning("Pattern generation failed for %s", account_id)
                    if (i + 1) % 5 == 0:
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
