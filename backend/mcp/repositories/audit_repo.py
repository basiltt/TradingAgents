"""AuditRepository — TASK-P0-02.

All SQL for mcp_audit_log. The single AuditWriter calls `last_chain` (to seed the
chain) and `append` (one row). `recover_dangling` stamps begin-without-end rows
as interrupted on boot (the gap-recovery contract).
"""
from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg


class AuditRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def last_chain(self) -> tuple[int, Optional[str]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT seq, entry_hash FROM mcp_audit_log ORDER BY seq DESC LIMIT 1"
            )
        if row is None:
            return (0, None)
        return (row["seq"], row["entry_hash"])

    async def append(self, record: dict[str, Any]) -> None:
        args_redacted = record.get("args_redacted")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mcp_audit_log
                  (seq, prev_hash, entry_hash, tool_name, tool_group, safety_class,
                   mutating, principal_token_id, session_id, correlation_id,
                   args_redacted, status, error, duration_ms)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14)
                """,
                record["seq"],
                record.get("prev_hash"),
                record["entry_hash"],
                record.get("tool_name"),
                record.get("tool_group"),
                record.get("safety_class"),
                bool(record.get("mutating", False)),
                record.get("principal_token_id"),
                record.get("session_id"),
                record.get("correlation_id"),
                json.dumps(args_redacted) if args_redacted is not None else None,
                record.get("status", "ok"),
                record.get("error"),
                record.get("duration_ms"),
            )

    async def recover_dangling(self) -> int:
        """Stamp any begin-without-end (status NULL) rows as interrupted. Returns
        the count repaired. (Defensive: status is NOT NULL in schema, so this is
        a no-op unless a future column allows pending rows.)"""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE mcp_audit_log SET status='interrupted' WHERE status IS NULL"
            )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT seq, tool_name, tool_group, status, duration_ms, started_at, "
                "principal_token_id, session_id FROM mcp_audit_log "
                "ORDER BY seq DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
