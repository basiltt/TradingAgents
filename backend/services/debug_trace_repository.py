"""SQL repository for auto-trade debug tracing tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import asyncpg


def _num(x):
    """Coerce a numeric value to Decimal exactly (via str) for NUMERIC COPY columns.

    asyncpg's binary COPY accepts a float for NUMERIC but coerces via Decimal(float),
    capturing IEEE-754 error — wrong on a money path. Decimal(str(x)) is exact.
    Passes None through unchanged. Used by bulk_insert (Task 3).
    """
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


class DebugTraceRepository:
    """All SQL for debug_* tables. Pure data access — no buffering or threading."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── config ────────────────────────────────────────────────
    async def get_config(self) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tracing_enabled, retention_days, symbol_decision_cap FROM debug_config WHERE id=1"
            )
        if row is None:
            return {"tracing_enabled": True, "retention_days": 60, "symbol_decision_cap": 200}
        return dict(row)

    async def update_config(
        self, *, tracing_enabled: Optional[bool] = None,
        retention_days: Optional[int] = None, symbol_decision_cap: Optional[int] = None,
    ) -> dict[str, Any]:
        sets, args, i = [], [], 1
        if tracing_enabled is not None:
            sets.append(f"tracing_enabled=${i}"); args.append(tracing_enabled); i += 1
        if retention_days is not None:
            sets.append(f"retention_days=${i}"); args.append(retention_days); i += 1
        if symbol_decision_cap is not None:
            sets.append(f"symbol_decision_cap=${i}"); args.append(symbol_decision_cap); i += 1
        if sets:
            sets.append("updated_at=now()")
            async with self._pool.acquire() as conn:
                await conn.execute(f"UPDATE debug_config SET {', '.join(sets)} WHERE id=1", *args)
        return await self.get_config()

    # ── run lifecycle ─────────────────────────────────────────
    async def create_run(
        self, *, scan_id: str, trigger_source: str = "unknown",
        schedule_id: Optional[str] = None, schedule_execution_id: Optional[int] = None,
        scan_started_at: Optional[datetime] = None, scan_completed_at: Optional[datetime] = None,
        config_snapshot: Optional[dict] = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO debug_runs
                  (scan_id, trigger_source, schedule_id, schedule_execution_id,
                   scan_started_at, scan_completed_at, exec_started_at, config_snapshot)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
                """,
                scan_id, trigger_source, schedule_id, schedule_execution_id,
                scan_started_at, scan_completed_at, datetime.now(timezone.utc),
                json.dumps(config_snapshot or {}),
            )

    async def finalize_run(
        self, run_id: int, *, phase_reached: str,
        total_symbols: int = 0, completed_symbols: int = 0, failed_symbols: int = 0,
        num_accounts: int = 0, dropped_event_count: int = 0,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE debug_runs SET
                  exec_completed_at=now(), phase_reached=$2,
                  total_symbols=$3, completed_symbols=$4, failed_symbols=$5,
                  num_accounts=$6, dropped_event_count=$7
                WHERE id=$1
                """,
                run_id, phase_reached, total_symbols, completed_symbols,
                failed_symbols, num_accounts, dropped_event_count,
            )
