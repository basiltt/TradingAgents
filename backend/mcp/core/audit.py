"""Audit hash-chain core + single-writer — TASK-P0-08.

Trading-free. The audit log is append-only and hash-chained: each row's
`entry_hash` covers `(seq, prev_hash, canonical(payload))`. A single serialized
writer task assigns `seq`/`prev_hash`/`entry_hash` so concurrent callers can
never fork the chain; `enqueue()` returns without blocking on the DB write.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Optional, Protocol


def _canonical(payload: dict[str, Any]) -> str:
    """Deterministic JSON (sorted keys) of the audit payload."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(*, seq: int, prev_hash: Optional[str], payload: dict[str, Any]) -> str:
    """SHA-256 over seq + prev_hash + canonical payload (plaintext, pre-encryption)."""
    material = f"{seq}|{prev_hash or ''}|{_canonical(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_chain(rows: list[dict[str, Any]]) -> bool:
    """Verify a list of rows ordered by seq. Each row needs seq/prev_hash/entry_hash/payload."""
    prev: Optional[str] = None
    expected_seq = rows[0]["seq"] if rows else 1
    for row in rows:
        if row["seq"] != expected_seq:
            return False
        if row["prev_hash"] != prev:
            return False
        recomputed = compute_entry_hash(
            seq=row["seq"], prev_hash=row["prev_hash"], payload=row["payload"]
        )
        if recomputed != row["entry_hash"]:
            return False
        prev = row["entry_hash"]
        expected_seq += 1
    return True


class AuditRepoProtocol(Protocol):
    async def last_chain(self) -> tuple[int, Optional[str]]: ...
    async def append(self, record: dict[str, Any]) -> None: ...


class AuditWriter:
    """Single serialized consumer that assigns seq/hashes and persists records.

    `enqueue()` is non-blocking; the writer task drains the queue and chains.
    """

    def __init__(self, repo: AuditRepoProtocol, *, maxsize: int = 10_000) -> None:
        self._repo = repo
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._task: Optional[asyncio.Task] = None
        self._seq: int = 0
        self._prev: Optional[str] = None
        self._seeded = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        seq, prev = await self._repo.last_chain()
        self._seq, self._prev, self._seeded = seq, prev, True
        self._task = asyncio.create_task(self._run())

    async def enqueue(self, payload: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            # synchronous fallback through the SAME serialization point
            await self._write_one(payload)

    async def _run(self) -> None:
        while True:
            payload = await self._queue.get()
            try:
                await self._write_one(payload)
            finally:
                self._queue.task_done()

    async def _write_one(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._seq += 1
            entry_hash = compute_entry_hash(seq=self._seq, prev_hash=self._prev, payload=payload)
            record = {
                **{k: payload.get(k) for k in (
                    "tool_name", "tool_group", "safety_class", "mutating",
                    "principal_token_id", "session_id", "correlation_id",
                    "args_redacted", "status", "error", "duration_ms",
                )},
                "seq": self._seq,
                "prev_hash": self._prev,
                "entry_hash": entry_hash,
                "audit_payload": payload,
            }
            await self._repo.append(record)
            self._prev = entry_hash

    async def drain(self) -> None:
        await self._queue.join()

    async def shutdown(self) -> None:
        await self.drain()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
