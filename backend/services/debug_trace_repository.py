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

    # ── bulk event insert ─────────────────────────────────────
    async def bulk_insert(
        self, *,
        account_traces: Optional[list[dict]] = None,
        lifecycle_events: Optional[list[dict]] = None,
        symbol_decisions: Optional[list[dict]] = None,
        exchange_snapshots: Optional[list[dict]] = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if account_traces:
                await conn.copy_records_to_table(
                    "debug_account_traces",
                    columns=[
                        "run_id", "account_id", "account_label", "execution_mode",
                        "final_stopped_reason", "gate_that_stopped", "rescued_by_recheck",
                        "base_capital", "equity_at_start", "positions_at_start_count",
                        "trades_executed", "trades_failed", "trades_skipped",
                        "rules_created", "config_snapshot",
                    ],
                    records=[(
                        r["run_id"], r["account_id"], r.get("account_label"),
                        r.get("execution_mode"), r.get("final_stopped_reason"),
                        r.get("gate_that_stopped"), bool(r.get("rescued_by_recheck", False)),
                        _num(r.get("base_capital")), _num(r.get("equity_at_start")),
                        r.get("positions_at_start_count"),
                        int(r.get("trades_executed", 0)), int(r.get("trades_failed", 0)),
                        int(r.get("trades_skipped", 0)),
                        json.dumps(r.get("rules_created", [])),
                        json.dumps(r.get("config_snapshot", {})),
                    ) for r in account_traces],
                )
            if lifecycle_events:
                await conn.copy_records_to_table(
                    "debug_lifecycle_events",
                    columns=["run_id", "account_id", "seq", "phase", "event_type", "detail", "ts"],
                    records=[(
                        r["run_id"], r["account_id"], int(r.get("seq", 0)),
                        r.get("phase", "unknown"), r["event_type"],
                        json.dumps(r.get("detail", {})),
                        r.get("ts") or datetime.now(timezone.utc),
                    ) for r in lifecycle_events],
                )
            if symbol_decisions:
                await conn.copy_records_to_table(
                    "debug_symbol_decisions",
                    columns=[
                        "run_id", "account_id", "phase", "symbol", "scan_score",
                        "scan_confidence", "scan_direction", "decision", "reason_code",
                        "reason_detail", "order_id", "ts",
                    ],
                    records=[(
                        r["run_id"], r["account_id"], r.get("phase", "unknown"), r["symbol"],
                        r.get("scan_score"), r.get("scan_confidence"), r.get("scan_direction"),
                        r["decision"], r["reason_code"], json.dumps(r.get("reason_detail", {})),
                        r.get("order_id"), r.get("ts") or datetime.now(timezone.utc),
                    ) for r in symbol_decisions],
                )
            if exchange_snapshots:
                await conn.copy_records_to_table(
                    "debug_exchange_snapshots",
                    columns=["run_id", "account_id", "gate", "positions", "position_count", "wallet", "equity", "ts"],
                    records=[(
                        r["run_id"], r["account_id"], r["gate"],
                        json.dumps(r.get("positions", [])), int(r.get("position_count", 0)),
                        json.dumps(r.get("wallet", {})), _num(r.get("equity")),
                        r.get("ts") or datetime.now(timezone.utc),
                    ) for r in exchange_snapshots],
                )

    # ── retention ─────────────────────────────────────────────
    async def delete_runs_older_than(self, retention_days: int, *, batch_size: int = 50) -> int:
        """Delete expired runs (CASCADE removes child rows). Deletes in capped batches
        so a large backlog doesn't cascade millions of child rows in one statement
        (which would hold locks / bloat WAL). batch_size is small because each run
        cascade-deletes thousands of child rows. Each batch is its own transaction."""
        total_deleted = 0
        while True:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM debug_runs WHERE id IN (
                        SELECT id FROM debug_runs
                        WHERE created_at < now() - ($1 || ' days')::interval
                        ORDER BY id LIMIT $2
                    )
                    """,
                    str(int(retention_days)), batch_size,
                )
            try:
                n = int(result.split()[-1])  # "DELETE N"
            except (ValueError, IndexError):
                n = 0
            total_deleted += n
            if n < batch_size:
                break
        return total_deleted

    async def recover_orphaned_runs(self) -> int:
        """Mark runs left non-finalized by a crash/restart as 'server_restart'.

        A run is orphaned when exec_completed_at IS NULL (open_run set exec_started_at
        but close_run never ran). Mirrors TradingCycleEngine._startup_recovery. Called
        once at startup, before any new runs are opened."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE debug_runs
                SET exec_completed_at = now(),
                    phase_reached = COALESCE(NULLIF(phase_reached, ''), 'created') || '+server_restart'
                WHERE exec_completed_at IS NULL
                """,
            )
        try:
            return int(result.split()[-1])  # "UPDATE N"
        except (ValueError, IndexError):
            return 0
