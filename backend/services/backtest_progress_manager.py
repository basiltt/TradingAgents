"""Real-time backtest progress: a tiny per-run pub/sub for step-by-step UI updates.

The backtest run path goes through several named, observable stages (load signals,
warm cache, load klines, build contexts, dry-run, drill-down fetch, simulate,
compute metrics, persist). This manager lets the service EMIT a structured event
for each stage transition, and lets a WebSocket endpoint SUBSCRIBE to the stream
for a single run so the frontend can show exactly what's happening instead of a
bare spinner.

Design (mirrors AccountWSManager's queue model, scoped per run):
- emit(run_id, event): append to the run's step history + fan out to live subscribers.
- subscribe(run_id) -> Queue: a late subscriber first drains the run's history (so
  it catches up on steps that already happened), then receives live events.
- history is bounded + dropped a short TTL after the run reaches a terminal stage,
  so memory can't grow without bound.

Events are plain JSON-serialisable dicts:
    {
      "type": "backtest_progress",
      "run_id": "...",
      "stage": "loading_klines",     # machine key (stable, for the UI step list)
      "label": "Loading price data", # human title
      "detail": "480 symbols",       # optional specifics
      "pct": 8,                      # overall 0-100 (matches progress_pct)
      "status": "active",           # active | done | failed
      "seq": 3,                      # monotonic per run (ordering / dedup)
      "ts": 1234567890.12,
    }
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

# Max events retained per run (history replay for late subscribers). The stage list
# is short (~12 stages, plus periodic simulate ticks), so this is generous.
_MAX_HISTORY = 200
# How long to keep a finished run's history after its terminal event, so a client
# that connects just after completion still sees the final state. Seconds.
_TERMINAL_RETENTION_S = 60.0


class BacktestProgressManager:
    """Per-run step-event pub/sub for real-time backtest progress."""

    def __init__(self) -> None:
        # run_id -> list of subscriber queues
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # run_id -> ordered event history (for replay)
        self._history: dict[str, list[dict[str, Any]]] = {}
        # run_id -> monotonic sequence counter
        self._seq: dict[str, int] = {}
        # run_id -> wall-clock time the run reached a terminal event (for GC)
        self._terminal_at: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Emit (called from the service, on the event loop)
    # ------------------------------------------------------------------ #
    def emit(
        self,
        run_id: str,
        stage: str,
        label: str,
        *,
        detail: str = "",
        pct: Optional[int] = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Record + fan out a progress event for a run. Returns the built event."""
        self._gc()
        seq = self._seq.get(run_id, 0) + 1
        self._seq[run_id] = seq
        event = {
            "type": "backtest_progress",
            "run_id": run_id,
            "stage": stage,
            "label": label,
            "detail": detail,
            "pct": pct,
            "status": status,
            "seq": seq,
            "ts": time.time(),
        }
        hist = self._history.setdefault(run_id, [])
        hist.append(event)
        if len(hist) > _MAX_HISTORY:
            del hist[: len(hist) - _MAX_HISTORY]
        if status in ("done", "failed") and stage in ("complete", "failed"):
            self._terminal_at[run_id] = time.time()
        # Fan out to live subscribers (drop on full queue — history covers catch-up).
        for q in list(self._subscribers.get(run_id, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    # ------------------------------------------------------------------ #
    # Subscribe (called from the WS endpoint)
    # ------------------------------------------------------------------ #
    def subscribe(self, run_id: str) -> asyncio.Queue:
        """Subscribe to a run's events. The returned queue is PRE-LOADED with the
        run's history so a late subscriber catches up before live events arrive."""
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        for ev in self._history.get(run_id, ()):  # replay history
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                break
        self._subscribers.setdefault(run_id, set()).add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(run_id, None)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        """Current step history for a run (e.g. for an initial REST snapshot)."""
        return list(self._history.get(run_id, ()))

    # ------------------------------------------------------------------ #
    # GC — drop finished runs' history after the retention window
    # ------------------------------------------------------------------ #
    def _gc(self) -> None:
        if not self._terminal_at:
            return
        now = time.time()
        expired = [
            rid for rid, t in self._terminal_at.items()
            if now - t > _TERMINAL_RETENTION_S
        ]
        for rid in expired:
            self._history.pop(rid, None)
            self._seq.pop(rid, None)
            self._terminal_at.pop(rid, None)
            # Leave any (rare) lingering subscribers to close on their own.
