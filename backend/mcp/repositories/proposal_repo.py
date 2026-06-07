"""ProposalRepository — TASK-P4-08.

All SQL for mcp_proposals. A proposal records a winning swept config + its target
(schedule_id + auto_trade_configs index) + the prior config (diff.before, for
revert) and its lifecycle status.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg

_VALID_TRANSITIONS = {
    "pending": {"approved", "rejected", "expired", "applied"},
    "approved": {"applied", "reverted"},
    "applied": {"reverted"},
    "rejected": set(),
    "expired": set(),
    "reverted": set(),
}

_DEFAULT_TTL_HOURS = 24


def _loads(v: Any) -> Any:
    if v is None or isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return v


def _row(r: asyncpg.Record) -> dict[str, Any]:
    d = dict(r)
    for k in ("config", "diff", "risk_verdict"):
        if k in d:
            d[k] = _loads(d[k])
    for k in ("id", "sweep_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("created_at", "expires_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


class ProposalRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        sweep_id: Optional[str],
        target_schedule_id: Optional[str],
        target_config_index: Optional[int],
        config: dict[str, Any],
        diff: dict[str, Any],
        risk_verdict: Optional[dict[str, Any]] = None,
        ttl_hours: int = _DEFAULT_TTL_HOURS,
        clock_now: Optional[datetime] = None,
    ) -> str:
        now = clock_now or datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)
        async with self._pool.acquire() as conn:
            pid = await conn.fetchval(
                """
                INSERT INTO mcp_proposals
                  (sweep_id, target_schedule_id, target_config_index, config, diff,
                   risk_verdict, status, expires_at)
                VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,'pending',$7)
                RETURNING id
                """,
                sweep_id, target_schedule_id, target_config_index,
                json.dumps(config), json.dumps(diff),
                json.dumps(risk_verdict) if risk_verdict is not None else None,
                expires,
            )
        return str(pid)

    async def get(self, proposal_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM mcp_proposals WHERE id=$1", proposal_id)
        return _row(r) if r else None

    async def list(self, *, status: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM mcp_proposals WHERE status=$1 ORDER BY created_at DESC LIMIT $2",
                    status, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM mcp_proposals ORDER BY created_at DESC LIMIT $1", limit
                )
        return [_row(r) for r in rows]

    async def transition(
        self, proposal_id: str, *, to_status: str, approver: Optional[str] = None,
        applied_config_version: Optional[str] = None,
    ) -> dict[str, Any]:
        """Validate + apply a status transition. Raises ValueError on an illegal
        transition or unknown proposal."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                r = await conn.fetchrow(
                    "SELECT status FROM mcp_proposals WHERE id=$1 FOR UPDATE", proposal_id
                )
                if r is None:
                    raise ValueError(f"proposal {proposal_id!r} not found")
                cur = r["status"]
                if to_status not in _VALID_TRANSITIONS.get(cur, set()):
                    raise ValueError(f"illegal transition {cur} -> {to_status}")
                await conn.execute(
                    "UPDATE mcp_proposals SET status=$1, approver=COALESCE($2,approver), "
                    "applied_config_version=COALESCE($3,applied_config_version) WHERE id=$4",
                    to_status, approver, applied_config_version, proposal_id,
                )
                row = await conn.fetchrow("SELECT * FROM mcp_proposals WHERE id=$1", proposal_id)
        return _row(row)

    async def pending_count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM mcp_proposals WHERE status='pending'"
            ) or 0
