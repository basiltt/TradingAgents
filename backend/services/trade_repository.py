"""Trade repository — data access layer for trade CRUD with optimistic locking.

Manages the trade state machine (pending → open → closing → closed/failed/cancelled)
with version-checked updates to prevent concurrent modification.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from base64 import b64decode, b64encode
from typing import Any

from backend.async_persistence import AsyncAnalysisDB

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "pending", "open", "partially_filled", "closing",
    "partially_closed", "closed", "failed", "cancelled",
}
TERMINAL_STATUSES = {"closed", "failed", "cancelled"}

VALID_TRANSITIONS = {
    "pending": {"open", "failed", "cancelled", "partially_filled"},
    "open": {"closing", "partially_closed"},
    "partially_filled": {"open", "closing"},
    "closing": {"closed", "open", "partially_closed"},
    "partially_closed": {"closing", "closed"},
}

SORT_COLUMNS = {
    "created_at": "t.created_at",
    "opened_at": "t.opened_at",
    "closed_at": "t.closed_at",
    "realized_pnl": "t.realized_pnl",
}

METADATA_ALLOWLIST = {
    "error_code", "error_message", "reason", "detected_at",
    "bybit_exec_id", "parent_trade_id", "child_qty",
}

SYMBOL_PATTERN = r"^[A-Z0-9/]{1,30}$"

UPDATABLE_COLUMNS = {
    "order_id", "entry_price", "avg_fill_price", "exit_price",
    "mark_price_at_open", "opened_at", "filled_qty",
    "stop_loss_price", "take_profit_price",
}

VALID_SIDES = {"Buy", "Sell"}

VALID_CLOSE_REASONS = {
    "take_profit", "stop_loss", "manual_single", "manual_close_all",
    "rule_triggered", "cycle_target", "cycle_drawdown", "external",
    "liquidation", "adl",
}

VALID_EVENT_TYPES = {
    "placed", "filled", "partially_filled", "close_requested",
    "closed", "cancelled", "failed", "reconciled",
    "tp_triggered", "sl_triggered", "amended",
}


class TradeNotFound(Exception):
    """Raised when a trade ID does not exist in the database."""
    pass


class InvalidStatusTransition(Exception):
    """Raised when a status change violates the trade state machine."""
    pass


class ConcurrentModification(Exception):
    """Raised when the trade version has changed since it was last read."""
    pass


class TradeRepository:
    """Data access layer for trades with optimistic locking and state machine enforcement.

    All write methods require an asyncpg connection and expected_version
    to prevent concurrent modification. Status transitions are validated
    against VALID_TRANSITIONS before execution.
    """
    def __init__(self, db: AsyncAnalysisDB) -> None:
        """Initialize with database adapter for trade persistence."""
        self._db = db

    def _validate_metadata(self, metadata: dict) -> None:
        """Validate metadata keys against allowlist and enforce 8KB size limit."""
        if not metadata:
            return
        invalid_keys = set(metadata.keys()) - METADATA_ALLOWLIST
        if invalid_keys:
            raise ValueError(f"Invalid metadata keys: {invalid_keys}")
        raw = json.dumps(metadata)
        if len(raw.encode("utf-8")) >= 8192:
            raise ValueError("Metadata exceeds 8KB limit")

    async def create_trade(
        self, conn, *, account_id: str, symbol: str, side: str,
        qty: float, leverage: int = 1, margin_mode: str = "isolated",
        order_type: str = "market", source: str = "manual",
        source_id: int | None = None, position_idx: int = 0,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
        mark_price_at_open: float | None = None,
        capital_pct: float | None = None,
        base_capital: float | None = None,
        signal_direction: str | None = None,
        trade_direction: str | None = None,
        take_profit_pct: float | None = None,
        stop_loss_pct: float | None = None,
        metadata: dict | None = None,
        actor: str = "user",
    ) -> dict:
        """Insert a new trade in 'pending' status and record a 'placed' event."""
        if not re.match(SYMBOL_PATTERN, symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        if side not in VALID_SIDES:
            raise ValueError(f"Invalid side: {side}")
        if metadata:
            self._validate_metadata(metadata)
        order_link_id = str(uuid.uuid4())
        row = await conn.fetchrow(
            """INSERT INTO trades (
                account_id, symbol, side, order_type, qty, leverage, margin_mode,
                position_idx, stop_loss_price, take_profit_price, mark_price_at_open,
                capital_pct, base_capital, signal_direction, trade_direction,
                take_profit_pct, stop_loss_pct, source, source_id,
                order_link_id, metadata
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                $16, $17, $18, $19, $20, $21
            ) RETURNING *""",
            account_id, symbol, side, order_type, qty, leverage, margin_mode,
            position_idx, stop_loss_price, take_profit_price, mark_price_at_open,
            capital_pct, base_capital, signal_direction, trade_direction,
            take_profit_pct, stop_loss_pct, source, source_id,
            order_link_id, json.dumps(metadata or {}),
        )
        trade = dict(row)
        await conn.execute(
            """INSERT INTO trade_events (trade_id, event_type, new_status, actor)
            VALUES ($1, 'placed', 'pending', $2)""",
            trade["id"], actor,
        )
        return trade

    async def update_trade_status(
        self, conn, *, trade_id: str, account_id: str,
        expected_version: int, new_status: str,
        updates: dict[str, Any] | None = None,
        event_type: str | None = None,
        actor: str = "system",
        event_payload: dict | None = None,
    ) -> dict | None:
        """Transition trade status with optimistic locking and record an audit event."""
        start = time.monotonic()
        tid = uuid.UUID(trade_id)

        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {new_status}")

        if event_type and event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {event_type}")

        if updates:
            invalid_cols = set(updates.keys()) - UPDATABLE_COLUMNS
            if invalid_cols:
                raise ValueError(f"Invalid update columns: {invalid_cols}")

        current = await conn.fetchrow(
            "SELECT status FROM trades WHERE id = $1 AND account_id = $2 FOR UPDATE",
            tid, account_id,
        )
        if not current:
            raise TradeNotFound(f"Trade {trade_id} not found")

        old_status = current["status"]
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidStatusTransition(
                f"Cannot transition from {old_status} to {new_status}"
            )

        set_parts = ["status = $1", "version = version + 1"]
        params: list[Any] = [new_status]
        if updates:
            for key, val in updates.items():
                idx = len(params) + 1
                set_parts.append(f"{key} = ${idx}")
                params.append(val)

        ver_idx = len(params) + 1
        id_idx = len(params) + 2
        acct_idx = len(params) + 3
        params.extend([expected_version, tid, account_id])

        result = await conn.fetchrow(
            f"UPDATE trades SET {', '.join(set_parts)} "
            f"WHERE id = ${id_idx} AND version = ${ver_idx} AND account_id = ${acct_idx} RETURNING *",
            *params,
        )
        if not result:
            raise ConcurrentModification(f"Trade {trade_id} was modified concurrently")

        trade = dict(result)

        if event_type:
            await conn.execute(
                """INSERT INTO trade_events
                (trade_id, event_type, old_status, new_status, actor, payload)
                VALUES ($1, $2, $3, $4, $5, $6)""",
                tid, event_type, old_status, new_status,
                actor, json.dumps(event_payload or {}),
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "trade_status_changed",
            extra={
                "trade_id": trade_id, "old_status": old_status,
                "new_status": new_status, "latency_ms": round(elapsed_ms, 1),
            },
        )
        return trade

    async def close_trade(
        self, conn, *, trade_id: str, account_id: str,
        expected_version: int, exit_price: float,
        realized_pnl: float, realized_pnl_pct: float,
        fees: float, net_pnl: float, close_reason: str,
    ) -> dict | None:
        """Finalize a trade as 'closed' with PnL data and version check."""
        tid = uuid.UUID(trade_id)
        if close_reason not in VALID_CLOSE_REASONS:
            raise ValueError(f"Invalid close_reason: {close_reason}")
        set_parts = [
            "status = $1", "version = version + 1",
            "exit_price = $2", "realized_pnl = $3",
            "realized_pnl_pct = $4", "fees = $5", "net_pnl = $6",
            "closed_at = NOW()", "close_reason = $7",
        ]
        params: list[Any] = [
            "closed", exit_price, realized_pnl,
            realized_pnl_pct, fees, net_pnl, close_reason,
        ]
        if close_rule_id:
            set_parts.append(f"close_rule_id = ${len(params) + 1}")
            params.append(uuid.UUID(close_rule_id))

        ver_idx = len(params) + 1
        id_idx = len(params) + 2
        acct_idx = len(params) + 3
        params.extend([expected_version, tid, account_id])

        current = await conn.fetchrow(
            "SELECT status FROM trades WHERE id = $1 AND account_id = $2 FOR UPDATE",
            tid, account_id,
        )
        if not current:
            raise TradeNotFound(f"Trade {trade_id} not found")
        old_status = current["status"]
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if "closed" not in allowed:
            raise InvalidStatusTransition(
                f"Cannot transition from {old_status} to closed"
            )

        result = await conn.fetchrow(
            f"UPDATE trades SET {', '.join(set_parts)} "
            f"WHERE id = ${id_idx} AND version = ${ver_idx} AND account_id = ${acct_idx} RETURNING *",
            *params,
        )
        if not result:
            raise ConcurrentModification(f"Trade {trade_id} was modified concurrently")

        trade = dict(result)
        await conn.execute(
            """INSERT INTO trade_events
            (trade_id, event_type, old_status, new_status, actor, payload)
            VALUES ($1, 'closed', $2, 'closed', 'system', $3)""",
            tid, old_status,
            json.dumps({"close_reason": close_reason}),
        )
        return trade

    async def reconcile_close(
        self, conn, *, trade_id: str, account_id: str,
        exit_price: float, realized_pnl: float,
        realized_pnl_pct: float, fees: float,
    ) -> dict:
        """Close a trade without version check, used for external/reconciliation closes."""
        tid = uuid.UUID(trade_id)
        if close_reason not in VALID_CLOSE_REASONS:
            raise ValueError(f"Invalid close_reason: {close_reason}")

        # Intentionally bypasses VALID_TRANSITIONS — reconciliation can force-close from any non-terminal status
        row = await conn.fetchrow(
            "SELECT status, version FROM trades WHERE id = $1 AND account_id = $2 "
            "AND status IN ('open', 'partially_filled', 'closing', 'partially_closed') "
            "FOR UPDATE",
            tid, account_id,
        )
        if not row:
            raise ConcurrentModification(
                f"Trade {trade_id} already closed or not found"
            )

        old_status = row["status"]
        expected_version = row["version"]
        result = await conn.fetchrow(
            "UPDATE trades SET status = 'closed', version = version + 1, "
            "exit_price = $1, realized_pnl = $2, realized_pnl_pct = $3, "
            "fees = $4, net_pnl = $5, closed_at = NOW(), close_reason = $6 "
            "WHERE id = $7 AND account_id = $8 AND version = $9 RETURNING *",
            exit_price, realized_pnl, realized_pnl_pct,
            fees, net_pnl, close_reason, tid, account_id, expected_version,
        )
        if not result:
            raise ConcurrentModification(
                f"Trade {trade_id} was modified concurrently during reconciliation"
            )
        trade = dict(result)

        await conn.execute(
            """INSERT INTO trade_events
            (trade_id, event_type, old_status, new_status, actor, payload)
            VALUES ($1, 'reconciled', $2, 'closed', 'reconciliation', $3)""",
            tid, old_status,
            json.dumps({"close_reason": close_reason}),
        )
        return trade

    async def get_trade(
        self, conn, *, account_id: str, trade_id: str,
    ) -> dict | None:
        """Fetch a single trade by account and trade ID. Returns None if not found."""
        row = await conn.fetchrow(
            "SELECT * FROM trades WHERE id = $1 AND account_id = $2",
            uuid.UUID(trade_id), account_id,
        )
        return dict(row) if row else None

    async def get_trade_with_events(
        self, conn, *, account_id: str, trade_id: str,
    ) -> dict | None:
        """Fetch a trade with its audit event history embedded as an 'events' list."""
        trade = await self.get_trade(conn, account_id=account_id, trade_id=trade_id)
        if not trade:
            return None
        events = await conn.fetch(
            "SELECT * FROM trade_events WHERE trade_id = $1 ORDER BY created_at ASC LIMIT 1000",
            uuid.UUID(trade_id),
        )
        trade["events"] = [dict(e) for e in events]
        return trade

    async def list_trades(
        self, conn, *, account_id: str,
        status: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        close_reason: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        sort: str = "created_at",
        cursor: str | None = None,
        limit: int = 50,
        include_total: bool = False,
        parent_trade_id: str | None = None,
    ) -> dict:
        """List trades for an account with filters, sorting, and cursor pagination."""
        if sort not in SORT_COLUMNS:
            raise ValueError(f"Invalid sort column: {sort}. Allowed: {list(SORT_COLUMNS.keys())}")
        sort_col = SORT_COLUMNS[sort]
        limit = min(limit, 200)

        if symbol and not re.match(SYMBOL_PATTERN, symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        if status and status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        if side and side not in VALID_SIDES:
            raise ValueError(f"Invalid side: {side}")

        conditions = ["t.account_id = $1"]
        params: list[Any] = [account_id]

        if status:
            params.append(status)
            conditions.append(f"t.status = ${len(params)}")
        if symbol:
            params.append(symbol)
            conditions.append(f"t.symbol = ${len(params)}")
        if side:
            params.append(side)
            conditions.append(f"t.side = ${len(params)}")
        if close_reason:
            if close_reason not in VALID_CLOSE_REASONS:
                raise ValueError(f"Invalid close_reason: {close_reason}")
            params.append(close_reason)
            conditions.append(f"t.close_reason = ${len(params)}")
        if from_date:
            params.append(from_date)
            conditions.append(f"t.created_at >= ${len(params)}::timestamptz")
        if to_date:
            params.append(to_date)
            conditions.append(f"t.created_at <= ${len(params)}::timestamptz")
        if parent_trade_id:
            params.append(uuid.UUID(parent_trade_id))
            conditions.append(f"t.parent_trade_id = ${len(params)}")

        base_where = " AND ".join(conditions)
        base_params = list(params)

        if cursor:
            if len(cursor.encode("utf-8")) > 256:
                raise ValueError("Cursor too long")
            try:
                decoded = b64decode(cursor).decode("utf-8")
                parts = decoded.split("|", 1)
                cursor_val = parts[0] if parts[0] != "NULL" else None
                cursor_id = uuid.UUID(parts[1])
            except Exception:
                raise ValueError("Invalid cursor format")

            if cursor_val is not None:
                params.append(cursor_val)
                params.append(cursor_id)
                conditions.append(
                    f"({sort_col}, t.id) < (${len(params) - 1}::timestamptz, ${len(params)})"
                    if sort in ("created_at", "opened_at", "closed_at")
                    else f"({sort_col}, t.id) < (${len(params) - 1}::numeric, ${len(params)})"
                )
            else:
                params.append(cursor_id)
                conditions.append(
                    f"({sort_col} IS NULL AND t.id < ${len(params)})"
                )

        where = " AND ".join(conditions)
        params.append(limit + 1)

        query = (
            f"SELECT t.* FROM trades t WHERE {where} "
            f"ORDER BY {sort_col} DESC NULLS LAST, t.id DESC "
            f"LIMIT ${len(params)}"
        )
        rows = await conn.fetch(query, *params)
        items = [dict(r) for r in rows]

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = None
        if has_more and items:
            last = items[-1]
            sort_val = last.get(sort)
            val_str = str(sort_val) if sort_val is not None else "NULL"
            raw = f"{val_str}|{last['id']}"
            next_cursor = b64encode(raw.encode("utf-8")).decode("utf-8")

        total = None
        if include_total:
            count_query = f"SELECT COUNT(*) FROM trades t WHERE {base_where}"
            total = await conn.fetchval(count_query, *base_params)

        return {
            "items": items,
            "cursor": next_cursor,
            "has_more": has_more,
            "total": total,
        }

    async def get_open_trades(
        self, conn, *, account_id: str, limit: int = 500,
    ) -> list[dict]:
        """Fetch all open/partially-filled trades for an account."""
        rows = await conn.fetch(
            "SELECT * FROM trades WHERE account_id = $1 "
            "AND status IN ('open', 'partially_filled') "
            "ORDER BY created_at DESC LIMIT $2",
            account_id, limit,
        )
        return [dict(r) for r in rows]

    async def get_trade_stats(
        self, conn, *, account_id: str,
    ) -> dict:
        """Compute aggregate trade statistics (total, open count, win rate, PnL) for one account."""
        row = await conn.fetchrow(
            """SELECT
                COUNT(*) as total_trades,
                COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(*), 0), 0) as win_rate,
                COALESCE(AVG(net_pnl), 0) as avg_pnl,
                COALESCE(SUM(net_pnl), 0) as total_pnl,
                AVG(EXTRACT(EPOCH FROM (closed_at - opened_at))) as avg_hold_time
            FROM trades
            WHERE account_id = $1
              AND status = 'closed'
              AND parent_trade_id IS NULL
              AND exit_price > 0""",
            account_id,
        )
        return {
            "total_trades": row["total_trades"],
            "win_rate": float(row["win_rate"] or 0),
            "avg_pnl": float(row["avg_pnl"] or 0),
            "total_pnl": float(row["total_pnl"] or 0),
            "avg_hold_time": float(row["avg_hold_time"]) if row["avg_hold_time"] else None,
        }

    async def list_trades_cross_account(
        self, conn, *,
        account_ids: list[str],
        status: list[str] | None = None,
        symbol: str | None = None,
        side: str | None = None,
        from_date=None,
        to_date=None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        cursor_last_id: str | None = None,
        cursor_last_sort_value: str | None = None,
    ) -> dict:
        """List trades across multiple accounts with filters and cursor pagination."""
        if sort_by not in SORT_COLUMNS:
            raise ValueError(f"Invalid sort column: {sort_by}")
        sort_col = SORT_COLUMNS[sort_by]
        limit = min(limit, 200)

        conditions = ["t.account_id = ANY($1::text[])"]
        params: list[Any] = [account_ids]

        if status:
            for s in status:
                if s not in VALID_STATUSES:
                    raise ValueError(f"Invalid status: {s}")
            params.append(status)
            conditions.append(f"t.status = ANY(${len(params)}::text[])")
        if symbol:
            if not re.match(SYMBOL_PATTERN, symbol):
                raise ValueError(f"Invalid symbol: {symbol}")
            params.append(symbol)
            conditions.append(f"t.symbol = ${len(params)}")
        if side:
            if side not in VALID_SIDES:
                raise ValueError(f"Invalid side: {side}")
            params.append(side)
            conditions.append(f"t.side = ${len(params)}")
        if from_date:
            params.append(from_date)
            conditions.append(f"t.created_at >= ${len(params)}::timestamptz")
        if to_date:
            params.append(to_date)
            conditions.append(f"t.created_at <= ${len(params)}::timestamptz")

        if cursor_last_id:
            cursor_uuid = uuid.UUID(cursor_last_id)
            op = ">" if sort_dir == "asc" else "<"
            if cursor_last_sort_value is not None:
                params.append(cursor_last_sort_value)
                params.append(cursor_uuid)
                cast = "::timestamptz" if sort_by in ("created_at", "opened_at", "closed_at") else "::numeric"
                conditions.append(
                    f"({sort_col}, t.id) {op} (${len(params) - 1}{cast}, ${len(params)})"
                )
            else:
                params.append(cursor_uuid)
                id_op = ">" if sort_dir == "asc" else "<"
                conditions.append(
                    f"({sort_col} IS NULL AND t.id {id_op} ${len(params)})"
                )

        where = " AND ".join(conditions)
        params.append(limit + 1)

        asc = sort_dir == "asc"
        order_dir = "ASC" if asc else "DESC"
        nulls = "NULLS FIRST" if asc else "NULLS LAST"
        query = (
            f"SELECT t.* FROM trades t WHERE {where} "
            f"ORDER BY {sort_col} {order_dir} {nulls}, t.id {order_dir} "
            f"LIMIT ${len(params)}"
        )
        rows = await conn.fetch(query, *params)
        items = [dict(r) for r in rows]

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = None
        if has_more and items:
            last = items[-1]
            sort_val = last.get(sort_by)
            val_str = str(sort_val) if sort_val is not None else "NULL"
            raw = f"{val_str}|{last['id']}"
            next_cursor = b64encode(raw.encode("utf-8")).decode("utf-8")

        return {"items": items, "cursor": next_cursor, "has_more": has_more}

    async def get_stats_cross_account(
        self, conn, *, account_ids: list[str],
    ) -> dict:
        """Compute aggregate trade stats across multiple accounts."""
        row = await conn.fetchrow(
            """SELECT
                COUNT(*) FILTER (WHERE status = 'closed' AND exit_price > 0 AND parent_trade_id IS NULL) as total_trades,
                COUNT(*) FILTER (WHERE status IN ('open', 'pending', 'partially_filled', 'closing', 'partially_closed') AND parent_trade_id IS NULL) as open_count,
                COALESCE(AVG(net_pnl) FILTER (WHERE status = 'closed' AND exit_price > 0 AND parent_trade_id IS NULL), 0) as avg_pnl,
                COALESCE(SUM(net_pnl) FILTER (WHERE status = 'closed' AND exit_price > 0 AND parent_trade_id IS NULL), 0) as total_pnl,
                CASE WHEN COUNT(*) FILTER (WHERE status = 'closed' AND exit_price > 0 AND parent_trade_id IS NULL) > 0
                    THEN COUNT(*) FILTER (WHERE status = 'closed' AND net_pnl > 0 AND exit_price > 0 AND parent_trade_id IS NULL)::float
                         / COUNT(*) FILTER (WHERE status = 'closed' AND exit_price > 0 AND parent_trade_id IS NULL)
                    ELSE 0 END as win_rate
            FROM trades
            WHERE account_id = ANY($1::text[])""",
            account_ids,
        )
        return {
            "total_trades": row["total_trades"],
            "open_count": row["open_count"],
            "win_rate": float(row["win_rate"] or 0),
            "avg_pnl": float(row["avg_pnl"] or 0),
            "total_pnl": float(row["total_pnl"] or 0),
        }

    async def create_child_trade(
        self, conn, *, parent_trade: dict,
        closed_qty: float, exit_price: float,
        realized_pnl: float, realized_pnl_pct: float,
        fees: float, net_pnl: float, close_reason: str,
        close_rule_id: str | None = None,
    ) -> dict:
        """Create a closed child trade from a partial close of the parent."""
        if close_reason not in VALID_CLOSE_REASONS:
            raise ValueError(f"Invalid close_reason: {close_reason}")
        child = await conn.fetchrow(
            """INSERT INTO trades (
                account_id, symbol, side, order_type, qty, leverage, margin_mode,
                position_idx, entry_price, avg_fill_price, exit_price,
                stop_loss_price, take_profit_price,
                status, parent_trade_id, realized_pnl, realized_pnl_pct,
                fees, net_pnl, close_reason, close_rule_id, closed_at, opened_at,
                source, source_id, order_link_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                'closed', $14, $15, $16, $17, $18, $19, $20, NOW(), $21, $22, $23, $24
            ) RETURNING *""",
            parent_trade["account_id"], parent_trade["symbol"],
            parent_trade["side"], parent_trade["order_type"],
            closed_qty, parent_trade["leverage"], parent_trade["margin_mode"],
            parent_trade["position_idx"],
            parent_trade.get("entry_price"), parent_trade.get("avg_fill_price"),
            exit_price,
            parent_trade.get("stop_loss_price"), parent_trade.get("take_profit_price"),
            parent_trade["id"], realized_pnl, realized_pnl_pct,
            fees, net_pnl, close_reason, close_rule_id,
            parent_trade.get("opened_at"),
            parent_trade["source"], parent_trade.get("source_id"),
            str(uuid.uuid4()),
        )
        child_dict = dict(child)

        await conn.execute(
            """INSERT INTO trade_events
            (trade_id, event_type, new_status, actor, payload)
            VALUES ($1, 'closed', 'closed', 'system', $2)""",
            child_dict["id"],
            json.dumps({"close_reason": close_reason, "parent_trade_id": str(parent_trade["id"])}),
        )

        return child_dict

    async def get_pending_orphans(
        self, conn, *, max_age_minutes: int = 5, limit: int = 100,
    ) -> list[dict]:
        """Find stale pending trades with no order_id for reconciliation cleanup."""
        # System-level query: intentionally cross-tenant for reconciliation cleanup
        rows = await conn.fetch(
            "SELECT * FROM trades WHERE status = 'pending' AND order_id IS NULL "
            "AND created_at < NOW() - INTERVAL '1 minute' * $1 LIMIT $2",
            max_age_minutes, limit,
        )
        return [dict(r) for r in rows]

    async def get_open_trades_by_symbol_side(
        self, conn, *, account_id: str, symbol: str, side: str,
    ) -> list[dict]:
        """Fetch open/partially-filled trades for a specific symbol and side."""
        if not re.match(SYMBOL_PATTERN, symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        if side not in VALID_SIDES:
            raise ValueError(f"Invalid side: {side}")
        rows = await conn.fetch(
            "SELECT * FROM trades WHERE account_id = $1 AND symbol = $2 AND side = $3 "
            "AND status IN ('open', 'partially_filled') ORDER BY created_at ASC",
            account_id, symbol, side,
        )
        return [dict(r) for r in rows]
