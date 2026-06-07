"""MCP leader election — G2-5 (FR-034), composition layer (touches asyncpg).

When WEB_CONCURRENCY>1, multiple worker processes share the DB but only ONE may
run the MCP server (a corruption guard: the hash-chained audit + single-writer
invariant assume one writer). This uses a SESSION-level Postgres advisory lock on
a DEDICATED, never-pooled connection held for the worker's lifetime — the first
worker to grab it is the leader; others degrade (MCP stays off in them).

`pg_try_advisory_lock` is non-blocking: a non-leader gets False immediately and
does not queue. The lock auto-releases if the connection drops (worker crash), so
leadership fails over naturally.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# A distinct lock key from the migration lock (8675309).
_MCP_LEADER_LOCK_KEY = 8675310


class MCPLeader:
    """Holds the leader advisory lock on a dedicated connection."""

    def __init__(self) -> None:
        self._conn: Optional[Any] = None
        self.is_leader = False

    async def acquire(self, dsn: str) -> bool:
        """Try to become the MCP leader (non-blocking). Returns True if leader.

        Opens a dedicated connection (NOT from the shared pool — it must not be
        recycled, or the session lock would release) and tries the advisory lock.
        """
        import asyncpg

        try:
            self._conn = await asyncpg.connect(dsn=dsn)
            got = await self._conn.fetchval("SELECT pg_try_advisory_lock($1)", _MCP_LEADER_LOCK_KEY)
            self.is_leader = bool(got)
            if not self.is_leader:
                await self._conn.close()
                self._conn = None
            return self.is_leader
        except Exception:  # noqa: BLE001 — leadership is best-effort; degrade to non-leader
            logger.exception("mcp_leader_acquire_failed")
            self.is_leader = False
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self._conn = None
            return False

    async def release(self) -> None:
        """Release the lock + close the dedicated connection (closing alone also
        releases a session-level advisory lock, but be explicit)."""
        if self._conn is not None:
            try:
                await self._conn.execute("SELECT pg_advisory_unlock($1)", _MCP_LEADER_LOCK_KEY)
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None
        self.is_leader = False
