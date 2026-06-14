"""Real-time post-scan auto-trade progress: a per-scan pub/sub for live UI updates.

The post-scan auto-trade "tail" (init_balances → execute_batch → fill →
post_scan_recheck → cleanup → account_summaries → complete) places real-money
orders. This manager lets the executor/scanner EMIT a structured event per stage
transition / per-account / per-order, and lets a WebSocket endpoint SUBSCRIBE to
one scan's stream so the frontend shows exactly what is happening live instead of
the old "everything appears at the end" 3s-poll behavior.

Mirrors BacktestProgressManager (same queue + history-replay model) but the event
schema carries the post-scan-specific fields (account, symbol, side, reason_code,
per-account counters, dry_run, cooloff). Machine-stable `stage`/`status`/
`reason_code` codes drive the UI; the free-text label/detail are advisory only and
are NOT emitted over the wire (the WS payload is built from codes — no secret/PII
leak via error strings).

Events are plain JSON-serialisable dicts:
    {
      "type": "scan_auto_trade_progress",
      "schema_version": 1,
      "scan_id": "...",
      "stage": "execute_batch",      # machine key (stable, for the UI step list)
      "status": "active",           # active | done | failed | skipped
      "pct": 40,                    # overall 0-100, or None
      "seq": 7,                      # monotonic per scan (ordering / dedup)
      "ts": 1234567890.12,
      # post-scan-specific (any may be None):
      "account_id": "...",          # internal id (server side only; see note)
      "acct_ordinal": 2,            # per-scan ordinal for the opaque UI handle
      "symbol": "BTCUSDT",
      "side": "buy",
      "phase": "batch",
      "reason_code": "max_trades",  # enumerated skip/outcome code
      "trades_executed": 3,          # cumulative per-account counters
      "trades_failed": 0,
      "trades_skipped": 1,
      "dry_run": false,
      "cooloff_until": null,         # absolute epoch for a ban cooloff countdown
      "substatus": null,            # e.g. "rate_wait" | "ban"
    }
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

SCHEMA_VERSION = 1

# Max events retained per scan for late-subscriber replay. A multi-account scan
# can emit one event per (account, symbol); keep generous but bounded.
_MAX_HISTORY = 500
# Keep a finished scan's history this long after its terminal event so a client
# that connects just after completion still sees the final state (seconds).
_TERMINAL_RETENTION_S = 60.0
# Per-subscriber queue size (drop-oldest on overflow; history covers catch-up).
_SUBSCRIBER_QUEUE_MAX = 256

_TERMINAL_STAGES = ("complete", "failed", "cancelled")


class ScanProgressManager:
    """Per-scan step-event pub/sub for real-time post-scan auto-trade progress."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._seq: dict[str, int] = {}
        self._terminal_at: dict[str, float] = {}

    def emit(
        self,
        scan_id: str,
        stage: str,
        label: str = "",
        *,
        status: str = "active",
        pct: Optional[int] = None,
        account_id: Optional[str] = None,
        acct_ordinal: Optional[int] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        phase: Optional[str] = None,
        reason_code: Optional[str] = None,
        trades_executed: Optional[int] = None,
        trades_failed: Optional[int] = None,
        trades_skipped: Optional[int] = None,
        dry_run: Optional[bool] = None,
        cooloff_until: Optional[float] = None,
        substatus: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record + fan out a progress event for a scan. Returns the built event.

        Never raises (callers treat progress as best-effort / fail-open). The
        free-text ``label`` is kept server-side for logging only and is NOT placed
        on the emitted payload — the UI renders from the machine codes.
        """
        self._gc()
        seq = self._seq.get(scan_id, 0) + 1
        self._seq[scan_id] = seq
        event: dict[str, Any] = {
            "type": "scan_auto_trade_progress",
            "schema_version": SCHEMA_VERSION,
            "scan_id": scan_id,
            "stage": stage,
            "status": status,
            "pct": pct,
            "seq": seq,
            "ts": time.time(),
            "account_id": account_id,
            "acct_ordinal": acct_ordinal,
            "symbol": symbol,
            "side": side,
            "phase": phase,
            "reason_code": reason_code,
            "trades_executed": trades_executed,
            "trades_failed": trades_failed,
            "trades_skipped": trades_skipped,
            "dry_run": dry_run,
            "cooloff_until": cooloff_until,
            "substatus": substatus,
        }
        hist = self._history.setdefault(scan_id, [])
        hist.append(event)
        if len(hist) > _MAX_HISTORY:
            # Keep the most recent events; the terminal event (always last) is retained.
            del hist[: len(hist) - _MAX_HISTORY]
        if status in ("done", "failed", "cancelled") and stage in _TERMINAL_STAGES:
            self._terminal_at[scan_id] = time.time()
        # Fan out to live subscribers (drop-oldest on a full queue — history covers
        # catch-up; a slow consumer must never block the emitter / trade execution).
        for q in list(self._subscribers.get(scan_id, ())):
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

    def subscribe(self, scan_id: str) -> asyncio.Queue:
        """Subscribe to a scan's events. The returned queue is PRE-LOADED with the
        scan's history so a late subscriber catches up before live events arrive."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
        for ev in self._history.get(scan_id, ()):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                break
        self._subscribers.setdefault(scan_id, set()).add(q)
        return q

    def unsubscribe(self, scan_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(scan_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(scan_id, None)

    def history(self, scan_id: str) -> list[dict[str, Any]]:
        """Current step history for a scan (e.g. for an initial REST snapshot)."""
        return list(self._history.get(scan_id, ()))

    def _gc(self) -> None:
        if not self._terminal_at:
            return
        now = time.time()
        expired = [
            sid for sid, t in self._terminal_at.items()
            if now - t > _TERMINAL_RETENTION_S
        ]
        for sid in expired:
            self._history.pop(sid, None)
            self._seq.pop(sid, None)
            self._terminal_at.pop(sid, None)
