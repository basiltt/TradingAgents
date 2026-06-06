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


def _build_narrative(node: dict) -> str:
    """Plain-English per-account story from the trace node."""
    aid = node.get("account_label") or node.get("account_id")
    reason = node.get("final_stopped_reason")
    executed = node.get("trades_executed", 0)
    skipped = node.get("trades_skipped", 0)
    rescued = node.get("rescued_by_recheck")
    parts = [f"Account {aid}:"]
    snaps = {s["gate"]: s for s in node.get("exchange_snapshots", [])}
    start = snaps.get("scan_start")
    recheck = snaps.get("recheck")
    if start:
        parts.append(f"at scan-start held {start['position_count']} position(s)")
    if reason == "positions_already_open":
        parts.append("→ skipped (positions already open at scan-start)")
    closes = node.get("linked_close_executions", []) or []
    if closes and start and start["position_count"] > 0:
        last_close = max(closes, key=lambda c: c.get("executed_at") or "")
        when = str(last_close.get("executed_at", ""))[:19]
        parts.append(f"→ prior positions closed during scan ({when})")
    elif recheck is not None and start and start["position_count"] > 0 and recheck["position_count"] == 0:
        parts.append("→ positions cleared during scan (recheck saw 0)")
    if rescued:
        parts.append("→ rescued by post-scan recheck")
    if executed:
        placed_syms = [d["symbol"] for d in node.get("symbol_decisions", []) if d.get("decision") == "placed"]
        sym_str = f" ({'/'.join(placed_syms[:6])})" if placed_syms else ""
        parts.append(f"→ placed {executed} trade(s){sym_str}")
    if skipped:
        parts.append(f"(skipped {skipped} candidate signals)")
    if not executed and reason and reason != "positions_already_open":
        parts.append(f"→ no trades (stopped: {reason})")
    return " ".join(parts)


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
                json.dumps(config_snapshot or {}, default=str),
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
                        json.dumps(r.get("rules_created", []), default=str),
                        json.dumps(r.get("config_snapshot", {}), default=str),
                    ) for r in account_traces],
                )
            if lifecycle_events:
                await conn.copy_records_to_table(
                    "debug_lifecycle_events",
                    columns=["run_id", "account_id", "seq", "phase", "event_type", "detail", "ts"],
                    records=[(
                        r["run_id"], r["account_id"], int(r.get("seq", 0)),
                        r.get("phase", "unknown"), r["event_type"],
                        json.dumps(r.get("detail", {}), default=str),
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
                        r["decision"], r["reason_code"], json.dumps(r.get("reason_detail", {}), default=str),
                        r.get("order_id"), r.get("ts") or datetime.now(timezone.utc),
                    ) for r in symbol_decisions],
                )
            if exchange_snapshots:
                await conn.copy_records_to_table(
                    "debug_exchange_snapshots",
                    columns=["run_id", "account_id", "gate", "positions", "position_count", "wallet", "equity", "ts"],
                    records=[(
                        r["run_id"], r["account_id"], r["gate"],
                        json.dumps(r.get("positions", []), default=str), int(r.get("position_count", 0)),
                        json.dumps(r.get("wallet", {}), default=str), _num(r.get("equity")),
                        r.get("ts") or datetime.now(timezone.utc),
                    ) for r in exchange_snapshots],
                )

    # ── retention ─────────────────────────────────────────────
    async def delete_runs_older_than(self, retention_days: int, *, batch_size: int = 50) -> int:
        """Delete expired runs (CASCADE removes child rows). Deletes in capped batches
        so a large backlog doesn't cascade millions of child rows in one statement
        (which would hold locks / bloat WAL). batch_size is small because each run
        cascade-deletes thousands of child rows. Each batch is its own transaction."""
        if batch_size < 1:
            batch_size = 50
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

    # ── reads ─────────────────────────────────────────────────
    async def get_latest_run_id_for_scan(self, scan_id: str) -> Optional[int]:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT id FROM debug_runs WHERE scan_id=$1 ORDER BY created_at DESC LIMIT 1",
                scan_id,
            )

    async def get_run_tree(self, run_id: int) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            run = await conn.fetchrow("SELECT * FROM debug_runs WHERE id=$1", run_id)
            if run is None:
                return {}
            accts = await conn.fetch("SELECT * FROM debug_account_traces WHERE run_id=$1 ORDER BY account_id", run_id)
            events = await conn.fetch("SELECT * FROM debug_lifecycle_events WHERE run_id=$1 ORDER BY account_id, seq", run_id)
            decisions = await conn.fetch("SELECT * FROM debug_symbol_decisions WHERE run_id=$1 ORDER BY account_id, ts", run_id)
            snaps = await conn.fetch("SELECT * FROM debug_exchange_snapshots WHERE run_id=$1 ORDER BY account_id, gate", run_id)
        by_acct_ev: dict[str, list] = {}
        for e in events:
            by_acct_ev.setdefault(e["account_id"], []).append(dict(e))
        by_acct_dec: dict[str, list] = {}
        for d in decisions:
            by_acct_dec.setdefault(d["account_id"], []).append(dict(d))
        by_acct_snap: dict[str, list] = {}
        for s in snaps:
            by_acct_snap.setdefault(s["account_id"], []).append(dict(s))
        accounts = []
        for a in accts:
            aid = a["account_id"]
            node = dict(a)
            node["lifecycle_events"] = by_acct_ev.get(aid, [])
            node["symbol_decisions"] = by_acct_dec.get(aid, [])
            node["exchange_snapshots"] = by_acct_snap.get(aid, [])
            node["linked_trades"] = await self._linked_trades_for_account(run, aid, by_acct_dec.get(aid, []))
            node["linked_close_rules"], node["linked_close_executions"] = \
                await self._linked_rules_and_closes(run, aid)
            node["narrative"] = _build_narrative(node)
            accounts.append(node)
        return {"run": dict(run), "accounts": accounts}

    async def _linked_trades_for_account(self, run, account_id: str, decisions: list[dict]) -> list[dict]:
        """Resulting trades for this account in this run, matched by placed order_id."""
        order_ids = [d.get("order_id") for d in decisions if d.get("decision") == "placed" and d.get("order_id")]
        if not order_ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, symbol, side, status, close_reason, opened_at, closed_at,
                       realized_pnl, order_id, scan_result_id
                FROM trades WHERE account_id=$1 AND order_id = ANY($2::text[])
                ORDER BY opened_at
                """,
                account_id, order_ids,
            )
        return [dict(r) for r in rows]

    async def _linked_rules_and_closes(self, run, account_id: str):
        """close_rules and close_executions for this account within the run's time window."""
        start = run["exec_started_at"]
        end = run["exec_completed_at"]
        if start is None:
            return [], []
        async with self._pool.acquire() as conn:
            rules = await conn.fetch(
                """
                SELECT id, trigger_type, threshold_value, reference_value, status,
                       created_at, triggered_at, expires_at
                FROM close_rules
                WHERE account_id=$1
                  AND created_at >= $2
                  AND created_at <= COALESCE($3, now()) + interval '5 minutes'
                ORDER BY created_at
                """,
                account_id, start, end,
            )
            closes = await conn.fetch(
                """
                SELECT id, rule_id, trigger_source, total_positions, closed_count,
                       failed_count, executed_at
                FROM close_executions
                WHERE account_id=$1
                  AND executed_at >= $2
                  AND executed_at <= COALESCE($3, now()) + interval '5 minutes'
                ORDER BY executed_at
                """,
                account_id, start, end,
            )
        return [dict(r) for r in rules], [dict(r) for r in closes]

    async def list_runs(self, *, limit: int = 20, offset: int = 0,
                        trigger_source: Optional[str] = None,
                        account_id: Optional[str] = None,
                        from_ts: Optional[str] = None,
                        to_ts: Optional[str] = None) -> dict[str, Any]:
        args: list = []
        join = ""
        where: list[str] = []
        if account_id:
            args.append(account_id)
            join = f"JOIN debug_account_traces a ON a.run_id=r.id AND a.account_id=${len(args)}"
        if trigger_source:
            args.append(trigger_source)
            where.append(f"r.trigger_source=${len(args)}")
        if from_ts:
            args.append(from_ts)
            where.append(f"r.created_at >= ${len(args)}::timestamptz")
        if to_ts:
            args.append(to_ts)
            where.append(f"r.created_at <= ${len(args)}::timestamptz")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT count(DISTINCT r.id) FROM debug_runs r {join} {clause}", *args
            )
            args.append(limit); limit_ph = len(args)
            args.append(offset); offset_ph = len(args)
            rows = await conn.fetch(
                f"SELECT DISTINCT r.* FROM debug_runs r {join} {clause} "
                f"ORDER BY r.created_at DESC LIMIT ${limit_ph} OFFSET ${offset_ph}",
                *args,
            )
        return {"items": [dict(r) for r in rows], "total": total or 0, "limit": limit, "offset": offset}

    async def get_account_timeline(self, account_id: str, *, limit: int = 50,
                                   from_ts: Optional[str] = None,
                                   to_ts: Optional[str] = None) -> list[dict]:
        args: list = [account_id]
        where = ["a.account_id=$1"]
        if from_ts:
            args.append(from_ts); where.append(f"r.created_at >= ${len(args)}::timestamptz")
        if to_ts:
            args.append(to_ts); where.append(f"r.created_at <= ${len(args)}::timestamptz")
        args.append(limit); limit_ph = len(args)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT a.*, r.scan_id, r.trigger_source, r.created_at AS run_created_at
                FROM debug_account_traces a JOIN debug_runs r ON r.id=a.run_id
                WHERE {' AND '.join(where)} ORDER BY r.created_at DESC LIMIT ${limit_ph}
                """,
                *args,
            )
        return [dict(r) for r in rows]

    async def get_symbol_decisions(self, symbol: str, *, scan_id: Optional[str] = None,
                                   limit: int = 200) -> list[dict]:
        async with self._pool.acquire() as conn:
            if scan_id:
                rows = await conn.fetch(
                    """
                    SELECT d.*, r.scan_id FROM debug_symbol_decisions d
                    JOIN debug_runs r ON r.id=d.run_id
                    WHERE d.symbol=$1 AND r.scan_id=$2 ORDER BY d.ts DESC LIMIT $3
                    """,
                    symbol, scan_id, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM debug_symbol_decisions WHERE symbol=$1 ORDER BY ts DESC LIMIT $2",
                    symbol, limit,
                )
        return [dict(r) for r in rows]
