"""In-memory, fail-open recorder for auto-trade debug tracing.

Performance contract (money path safety):
- emit_* methods are synchronous, do no I/O, never raise, never block.
- On a full buffer, events are dropped and counted (never backpressure trading).
- A single boolean short-circuits all emits when tracing is disabled.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_BUFFER_MAX = 50_000


# Wallet fields retained in snapshots (spec §10 — sanitize before persisting).
_WALLET_FIELDS = (
    "totalEquity", "totalWalletBalance", "totalAvailableBalance",
    "totalMarginBalance", "totalPerpUPL", "totalInitialMargin", "totalMaintenanceMargin",
)

def _sanitize_wallet(wallet) -> dict:
    """Keep only known balance fields from a wallet payload. Defensive allow-list."""
    if not isinstance(wallet, dict):
        return {}
    return {k: wallet.get(k) for k in _WALLET_FIELDS if k in wallet}


@dataclass
class RunContext:
    """Per-run accumulator. Cheap to create; holds no locks."""
    scan_id: str
    trigger_source: str = "unknown"
    schedule_id: Optional[str] = None
    schedule_execution_id: Optional[int] = None
    run_id: Optional[int] = None
    dropped_event_count: int = 0
    _seq: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _symbol_counts: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    _truncated_marked: set = field(default_factory=set)

    def next_seq(self, account_id: str) -> int:
        n = self._seq[account_id]
        self._seq[account_id] = n + 1
        return n


class DebugTraceRecorder:
    """In-memory, fail-open trace recorder.

    THREADING INVARIANT (load-bearing): all emit_*/drain_once calls MUST run on the
    application's single asyncio event-loop thread. The buffer snapshot-then-clear in
    drain_once and the lazy _drain_lock initialization are only safe because no other
    thread mutates the buffer concurrently. This class is NOT thread-safe — never call
    emit_* from a worker thread / run_in_executor / asyncio.to_thread.
    """

    def __init__(self, repository: Any, *, buffer_max: int = _DEFAULT_BUFFER_MAX) -> None:
        self._repo = repository
        self._buffer: deque = deque(maxlen=buffer_max)
        self._buffer_max = buffer_max
        self._enabled = True
        self._symbol_decision_cap = 200
        self._retention_days = 60
        self._drainer_task = None
        self._cleanup_task = None
        self._running = False
        self._drain_lock = None          # lazily created asyncio.Lock (no loop at __init__)
        self._drain_count = 0            # drains since last config refresh (cadence control)

    @property
    def repo(self) -> Any:
        """Public accessor for the repository (read-side API uses this; avoids
        reaching into the private attribute from the router)."""
        return self._repo

    # ── introspection (used by tests) ─────────────────────────
    def buffered_count(self) -> int:
        return len(self._buffer)

    def snapshot_buffer(self) -> list[dict]:
        return list(self._buffer)

    # ── run context ───────────────────────────────────────────
    def new_run_context(self, *, scan_id: str, trigger_source: str = "unknown",
                        schedule_id: Optional[str] = None,
                        schedule_execution_id: Optional[int] = None) -> RunContext:
        return RunContext(
            scan_id=scan_id, trigger_source=trigger_source,
            schedule_id=schedule_id, schedule_execution_id=schedule_execution_id,
        )

    # ── internal: append with drop-on-pressure ────────────────
    def _append(self, ctx: RunContext, record: dict) -> None:
        if len(self._buffer) >= self._buffer_max:
            ctx.dropped_event_count += 1
            return
        self._buffer.append(record)

    # ── emit methods (sync, fail-open) ────────────────────────
    def emit_lifecycle(self, ctx: RunContext, *, account_id: str, phase: str,
                       event_type: str, detail: Optional[dict] = None) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            self._append(ctx, {
                "_table": "lifecycle_events",
                "run_id": ctx.run_id, "account_id": account_id,
                "seq": ctx.next_seq(account_id), "phase": phase,
                "event_type": event_type, "detail": detail or {},
                "ts": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("emit_lifecycle_failed", exc_info=True)

    def emit_symbol_decision(self, ctx: RunContext, *, account_id: str, phase: str,
                             symbol: str, decision: str, reason_code: str,
                             reason_detail: Optional[dict] = None,
                             scan_score=None, scan_confidence=None,
                             scan_direction=None, order_id=None) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            key = (account_id, phase)
            count = ctx._symbol_counts[key]
            if count >= self._symbol_decision_cap:
                if key not in ctx._truncated_marked:
                    ctx._truncated_marked.add(key)
                    self._append(ctx, {
                        "_table": "symbol_decisions", "run_id": ctx.run_id,
                        "account_id": account_id, "phase": phase, "symbol": "*",
                        "decision": "skipped", "reason_code": "truncated",
                        "reason_detail": {"cap": self._symbol_decision_cap},
                        "scan_score": None, "scan_confidence": None,
                        "scan_direction": None, "order_id": None,
                        "ts": datetime.now(timezone.utc),
                    })
                return
            ctx._symbol_counts[key] = count + 1
            self._append(ctx, {
                "_table": "symbol_decisions", "run_id": ctx.run_id,
                "account_id": account_id, "phase": phase, "symbol": symbol,
                "decision": decision, "reason_code": reason_code,
                "reason_detail": reason_detail or {},
                "scan_score": scan_score, "scan_confidence": scan_confidence,
                "scan_direction": scan_direction, "order_id": order_id,
                "ts": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("emit_symbol_decision_failed", exc_info=True)

    def emit_exchange_snapshot(self, ctx: RunContext, *, account_id: str, gate: str,
                               positions: Optional[list] = None,
                               wallet: Optional[dict] = None, equity=None) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            pos = list(positions) if positions else []
            wal = _sanitize_wallet(wallet)
            self._append(ctx, {
                "_table": "exchange_snapshots", "run_id": ctx.run_id,
                "account_id": account_id, "gate": gate, "positions": pos,
                "position_count": len(pos), "wallet": wal,
                "equity": equity, "ts": datetime.now(timezone.utc),
            })
        except Exception:
            logger.debug("emit_exchange_snapshot_failed", exc_info=True)

    def emit_account_trace(self, ctx: RunContext, *, account_id: str, **fields: Any) -> None:
        if not self._enabled or ctx.run_id is None:
            return
        try:
            rec = {"_table": "account_traces", "run_id": ctx.run_id, "account_id": account_id}
            rec.update(fields)
            self._append(ctx, rec)
        except Exception:
            logger.debug("emit_account_trace_failed", exc_info=True)

    # ── run open/close (async — called off the hot path) ──────
    async def open_run(self, ctx: RunContext, *, config_snapshot: Optional[dict] = None,
                       scan_started_at=None, scan_completed_at=None) -> None:
        # Kill-switch: when tracing is disabled, do NOT create a run row at all.
        # Leaving ctx.run_id = None makes every emit AND close_run a no-op, so a
        # disabled recorder writes nothing to the DB (not even empty run shells).
        if not self._enabled:
            ctx.run_id = None
            return
        try:
            ctx.run_id = await self._repo.create_run(
                scan_id=ctx.scan_id, trigger_source=ctx.trigger_source,
                schedule_id=ctx.schedule_id, schedule_execution_id=ctx.schedule_execution_id,
                scan_started_at=scan_started_at, scan_completed_at=scan_completed_at,
                config_snapshot=config_snapshot or {},
            )
        except Exception:
            logger.warning("debug_open_run_failed", exc_info=True)
            ctx.run_id = None  # disables emits for this run; trading unaffected

    async def close_run(self, ctx: RunContext, *, phase_reached: str,
                        total_symbols: int = 0, completed_symbols: int = 0,
                        failed_symbols: int = 0, num_accounts: int = 0) -> None:
        try:
            await self.drain_once()
            if ctx.run_id is not None:
                await self._repo.finalize_run(
                    ctx.run_id, phase_reached=phase_reached,
                    total_symbols=total_symbols, completed_symbols=completed_symbols,
                    failed_symbols=failed_symbols, num_accounts=num_accounts,
                    dropped_event_count=ctx.dropped_event_count,
                )
        except Exception:
            logger.warning("debug_close_run_failed", exc_info=True)

    # ── drainer ───────────────────────────────────────────────
    async def drain_once(self) -> None:
        # Serialize drains: drain_once is called from the periodic loop, close_run,
        # and shutdown. Without this lock, two drains could run overlapping bulk
        # inserts on the pool. The lock is created lazily (no event loop at __init__).
        if self._drain_lock is None:
            import asyncio
            self._drain_lock = asyncio.Lock()
        async with self._drain_lock:
            if not self._buffer:
                return
            # Snapshot and clear quickly (single-threaded event loop — safe; the
            # snapshot+clear has no await between the two statements).
            batch = list(self._buffer)
            self._buffer.clear()
            grouped: dict[str, list[dict]] = {
                "account_traces": [], "lifecycle_events": [],
                "symbol_decisions": [], "exchange_snapshots": [],
            }
            for rec in batch:
                grouped.get(rec["_table"], []).append(rec)
            # Insert each table INDEPENDENTLY so a failure in one table (poison record
            # or transient error) does not discard the other three. Data for a failed
            # table is lost for this batch — logged — but trading is unaffected.
            for table, rows in grouped.items():
                if not rows:
                    continue
                try:
                    await self._repo.bulk_insert(**{table: rows})
                except Exception:
                    logger.warning("debug_drain_table_failed", extra={"table": table, "count": len(rows)}, exc_info=True)

    async def refresh_config(self) -> None:
        try:
            cfg = await self._repo.get_config()
            self._enabled = bool(cfg.get("tracing_enabled", True))
            self._retention_days = int(cfg.get("retention_days", 60))
            self._symbol_decision_cap = int(cfg.get("symbol_decision_cap", 200))
        except Exception:
            logger.warning("debug_refresh_config_failed", exc_info=True)

    # ── lifecycle (lifespan-managed) ──────────────────────────
    async def start(self, *, drain_interval_s: float = 3.0, cleanup_interval_s: float = 86400.0,
                    initial_cleanup_delay_s: float = 300.0) -> None:
        import asyncio
        if self._drain_lock is None:
            self._drain_lock = asyncio.Lock()   # create on the running loop (not __init__)
        await self.refresh_config()
        # Reconcile runs orphaned by a previous crash/restart BEFORE any new run opens,
        # so they don't masquerade as in-progress. Best-effort; never blocks startup.
        try:
            n = await self._repo.recover_orphaned_runs()
            if n:
                logger.info("debug_recovered_orphaned_runs", extra={"count": n})
        except Exception:
            logger.warning("debug_recover_orphaned_runs_failed", exc_info=True)
        self._running = True
        self._drainer_task = asyncio.create_task(self._drain_loop(drain_interval_s))
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(cleanup_interval_s, initial_cleanup_delay_s))

    async def shutdown(self) -> None:
        import asyncio
        self._running = False
        for t in (self._drainer_task, self._cleanup_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        await self.drain_once()  # final flush

    async def _drain_loop(self, interval_s: float) -> None:
        import asyncio
        # Refresh config roughly every ~30s (every Nth drain), not every drain — the
        # PUT /config endpoint already refreshes immediately, so the loop only needs a
        # slow safety re-sync. At interval_s=3 this is ~10 drains; min 1.
        refresh_every = max(1, int(30 / interval_s)) if interval_s > 0 else 1
        while self._running:
            try:
                await asyncio.sleep(interval_s)
                self._drain_count += 1
                if self._drain_count % refresh_every == 0:
                    await self.refresh_config()
                await self.drain_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("debug_drain_loop_error", exc_info=True)

    async def _cleanup_loop(self, interval_s: float, initial_delay_s: float = 300.0) -> None:
        import asyncio
        # Run an initial cleanup shortly after startup (not after a full interval).
        # Otherwise a server that restarts more often than `interval_s` (e.g. daily
        # deploys vs a 24h interval) would NEVER run retention → unbounded growth.
        first = True
        while self._running:
            try:
                await asyncio.sleep(initial_delay_s if first else interval_s)
                first = False
                deleted = await self._repo.delete_runs_older_than(self._retention_days)
                if deleted:
                    logger.info("debug_retention_deleted", extra={"count": deleted})
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("debug_cleanup_loop_error", exc_info=True)
