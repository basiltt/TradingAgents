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
    phase_reached: str = "created"
    _seq: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _symbol_counts: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    _truncated_marked: set = field(default_factory=set)

    def next_seq(self, account_id: str) -> int:
        n = self._seq[account_id]
        self._seq[account_id] = n + 1
        return n


class DebugTraceRecorder:
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
