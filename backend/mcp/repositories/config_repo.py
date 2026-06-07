"""MCPConfigRepository — TASK-P0-02.

All SQL for the mcp_config singleton. Returns a typed view; enforces optimistic
concurrency on writes; boot-repairs an incomplete/missing row to fail-safe.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import asyncpg

from backend.mcp.core.errors import MCPConflictError

_FAILSAFE_FLAGS = {"read_only": True, "allow_real_trades": False, "allow_debug": False}


@dataclass(frozen=True)
class MCPConfig:
    enabled: bool
    bind_host: str
    access_token_hash: Optional[str]
    capability_tier: str
    enabled_groups: list[str]
    enabled_tools: dict[str, bool]
    safe_mode_flags: dict[str, bool]
    row_version: int
    config_epoch: int
    kill_epoch: int
    installation_id: str
    audit_retention_days: int
    sweep_retention_days: int
    egress_consent_at: Optional[str] = None


def _loads(v: Any, default: Any) -> Any:
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


def _row_to_config(row: asyncpg.Record) -> MCPConfig:
    flags = _loads(row["safe_mode_flags"], dict(_FAILSAFE_FLAGS))
    # most-restrictive on a corrupt/partial flags blob (R-308)
    if not isinstance(flags, dict) or "read_only" not in flags:
        flags = dict(_FAILSAFE_FLAGS)
    # egress_consent_at may be absent on a record selected before the v45 column
    consent = row["egress_consent_at"] if "egress_consent_at" in row else None
    return MCPConfig(
        enabled=row["enabled"],
        bind_host=row["bind_host"],
        access_token_hash=row["access_token_hash"],
        capability_tier=row["capability_tier"],
        enabled_groups=_loads(row["enabled_groups"], []),
        enabled_tools=_loads(row["enabled_tools"], {}),
        safe_mode_flags=flags,
        row_version=row["row_version"],
        config_epoch=row["config_epoch"],
        kill_epoch=row["kill_epoch"],
        installation_id=str(row["installation_id"]),
        audit_retention_days=row["audit_retention_days"],
        sweep_retention_days=row["sweep_retention_days"],
        egress_consent_at=(
            consent.isoformat()
            if consent is not None and hasattr(consent, "isoformat")
            else None
        ),
    )


class MCPConfigRepository:
    """Data access for the mcp_config singleton."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self) -> MCPConfig:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mcp_config WHERE id=1")
        if row is None:
            # absent row reads as the fail-safe default (disabled)
            return MCPConfig(
                enabled=False, bind_host="127.0.0.1", access_token_hash=None,
                capability_tier="READ_ONLY", enabled_groups=[], enabled_tools={},
                safe_mode_flags=dict(_FAILSAFE_FLAGS), row_version=0, config_epoch=0,
                kill_epoch=0, installation_id="", audit_retention_days=365,
                sweep_retention_days=90,
            )
        return _row_to_config(row)

    async def update(self, patch: dict[str, Any], *, expected_row_version: int) -> MCPConfig:
        """Optimistic-concurrency single-row update. Raises MCPConflictError on
        a row_version mismatch."""
        sets: list[str] = []
        args: list[Any] = []
        i = 1
        for key in (
            "enabled", "bind_host", "access_token_hash", "capability_tier",
            "audit_retention_days", "sweep_retention_days",
        ):
            if key in patch:
                sets.append(f"{key}=${i}")
                args.append(patch[key])
                i += 1
        for jkey in ("enabled_groups", "enabled_tools", "safe_mode_flags"):
            if jkey in patch:
                sets.append(f"{jkey}=${i}::jsonb")
                args.append(json.dumps(patch[jkey]))
                i += 1
        sets.append("row_version=row_version+1")
        sets.append("config_epoch=config_epoch+1")
        sets.append("updated_at=now()")
        args.append(expected_row_version)
        sql = (
            f"UPDATE mcp_config SET {', '.join(sets)} "
            f"WHERE id=1 AND row_version=${i} RETURNING *"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
        if row is None:
            raise MCPConflictError("mcp_config was modified concurrently (row_version mismatch)")
        return _row_to_config(row)

    async def set_token_hash(self, token_hash: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE mcp_config SET access_token_hash=$1, row_version=row_version+1, "
                "updated_at=now() WHERE id=1",
                token_hash,
            )

    async def record_egress_consent(self) -> str:
        """Record the one-time data-egress consent (FR-033). Idempotent: only
        sets the timestamp the FIRST time (COALESCE keeps the original). Returns
        the consent timestamp ISO string."""
        async with self._pool.acquire() as conn:
            ts = await conn.fetchval(
                "UPDATE mcp_config SET egress_consent_at=COALESCE(egress_consent_at, now()) "
                "WHERE id=1 RETURNING egress_consent_at"
            )
        return ts.isoformat() if ts is not None and hasattr(ts, "isoformat") else str(ts)

    async def bump_kill_epoch(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE mcp_config SET kill_epoch=kill_epoch+1, enabled=false, "
                "config_epoch=config_epoch+1, updated_at=now() WHERE id=1 RETURNING kill_epoch"
            )

    async def repair_to_failsafe(self) -> None:
        """Boot-repair: ensure the singleton exists with valid fail-safe flags;
        force OFF if the row is incomplete/corrupt."""
        async with self._pool.acquire() as conn:
            await conn.execute("INSERT INTO mcp_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            row = await conn.fetchrow("SELECT safe_mode_flags FROM mcp_config WHERE id=1")
            flags = _loads(row["safe_mode_flags"], None)
            if not isinstance(flags, dict) or "read_only" not in flags:
                await conn.execute(
                    "UPDATE mcp_config SET safe_mode_flags=$1::jsonb, enabled=false WHERE id=1",
                    json.dumps(_FAILSAFE_FLAGS),
                )
