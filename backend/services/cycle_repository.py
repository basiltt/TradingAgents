"""Repository for trading_cycles and cycle_trades CRUD operations."""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_STATUS_UPDATABLE_COLS = frozenset({
    "initial_equity", "final_pnl", "stop_reason",
    "trades_placed", "trades_failed", "started_at", "completed_at",
})

_TRADE_UPDATABLE_COLS = frozenset({
    "order_id", "qty", "entry_price", "status", "error_msg", "filled_at",
})

_TERMINAL_STATUSES = frozenset({"completed", "stopped", "failed"})

_ACTIVE_STATUSES = ("pending", "placing_trades", "running", "stopping")


class CycleRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create_cycle(self, config: dict) -> int:
        row = await self._pool.fetchrow(
            """
            INSERT INTO trading_cycles (
                account_id, scan_id, trade_direction, leverage, capital_pct,
                take_profit_pct, stop_loss_pct, min_score, min_confidence,
                signal_filter, max_trades, target_type, target_value,
                max_drawdown_pct
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            RETURNING id
            """,
            config["account_id"], config.get("scan_id"),
            config["trade_direction"], config["leverage"], config["capital_pct"],
            config.get("take_profit_pct"), config.get("stop_loss_pct"),
            config["min_score"], config["min_confidence"],
            config["signal_filter"], config["max_trades"],
            config["target_type"], config["target_value"],
            config["max_drawdown_pct"],
        )
        return row["id"]

    async def get_cycle(self, cycle_id: int) -> Optional[dict]:
        cycle = await self._pool.fetchrow(
            "SELECT * FROM trading_cycles WHERE id = $1", cycle_id
        )
        if not cycle:
            return None
        result = dict(cycle)
        trades = await self._pool.fetch(
            "SELECT * FROM cycle_trades WHERE cycle_id = $1 ORDER BY created_at",
            cycle_id,
        )
        result["trades"] = [dict(t) for t in trades]
        return result

    async def list_cycles(
        self, offset: int = 0, limit: int = 20, *, status: Optional[str] = None
    ) -> tuple[list[dict], int]:
        if status == "active":
            where = "WHERE status = ANY($1::text[])"
            params: list = [list(_ACTIVE_STATUSES)]
            count_params: list = [list(_ACTIVE_STATUSES)]
        elif status:
            where = "WHERE status = $1"
            params = [status]
            count_params = [status]
        else:
            where = ""
            params = []
            count_params = []

        total_row = await self._pool.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM trading_cycles {where}",
            *count_params,
        )
        total = total_row["cnt"]

        idx = len(params) + 1
        rows = await self._pool.fetch(
            f"SELECT * FROM trading_cycles {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params, limit, offset,
        )
        return [dict(r) for r in rows], total

    async def update_status(
        self, cycle_id: int, new_status: str, **kwargs
    ) -> bool:
        bad_keys = set(kwargs) - _STATUS_UPDATABLE_COLS
        if bad_keys:
            raise ValueError(f"Invalid update columns: {bad_keys}")

        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT status FROM trading_cycles WHERE id = $1 FOR UPDATE",
                cycle_id,
            )
            if not row:
                return False
            if row["status"] in _TERMINAL_STATUSES:
                return False

            sets = ["status = $2"]
            vals: list = [cycle_id, new_status]
            for i, (col, val) in enumerate(kwargs.items(), start=3):
                sets.append(f"{col} = ${i}")
                vals.append(val)

            await conn.execute(
                f"UPDATE trading_cycles SET {', '.join(sets)} WHERE id = $1",
                *vals,
            )
            return True

    async def add_trade(self, cycle_id: int, trade_data: dict) -> int:
        error_msg = trade_data.get("error_msg")
        if error_msg and len(error_msg) > 500:
            error_msg = error_msg[:500]
        row = await self._pool.fetchrow(
            """
            INSERT INTO cycle_trades (cycle_id, symbol, order_link_id, side, status, error_msg)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            cycle_id, trade_data["symbol"], trade_data.get("order_link_id"),
            trade_data["side"], trade_data.get("status", "pending"),
            error_msg,
        )
        return row["id"]

    async def update_trade(self, trade_id: int, **kwargs) -> None:
        bad_keys = set(kwargs) - _TRADE_UPDATABLE_COLS
        if bad_keys:
            raise ValueError(f"Invalid trade update columns: {bad_keys}")

        if "error_msg" in kwargs and kwargs["error_msg"] and len(kwargs["error_msg"]) > 500:
            kwargs["error_msg"] = kwargs["error_msg"][:500]

        sets = []
        vals: list = [trade_id]
        for i, (col, val) in enumerate(kwargs.items(), start=2):
            sets.append(f"{col} = ${i}")
            vals.append(val)

        if sets:
            await self._pool.execute(
                f"UPDATE cycle_trades SET {', '.join(sets)} WHERE id = $1",
                *vals,
            )

    async def increment_counters(self, cycle_id: int, placed: int = 0, failed: int = 0) -> None:
        await self._pool.execute(
            """
            UPDATE trading_cycles
            SET trades_placed = trades_placed + $2,
                trades_failed = trades_failed + $3
            WHERE id = $1
            """,
            cycle_id, placed, failed,
        )

    async def find_stuck_cycles(self, max_age_seconds: int) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM trading_cycles
            WHERE status IN ('running', 'placing_trades', 'stopping')
              AND created_at < NOW() - make_interval(secs => $1::int)
            """,
            max_age_seconds,
        )
        return [dict(r) for r in rows]

    async def find_all_non_terminal_cycles(self) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM trading_cycles
            WHERE status IN ('pending', 'running', 'placing_trades', 'stopping')
            """,
        )
        return [dict(r) for r in rows]

    async def reconcile_counters(self, cycle_id: int) -> None:
        row = await self._pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'filled') AS placed,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed
            FROM cycle_trades WHERE cycle_id = $1
            """,
            cycle_id,
        )
        await self._pool.execute(
            """
            UPDATE trading_cycles
            SET trades_placed = $2, trades_failed = $3
            WHERE id = $1
            """,
            cycle_id, row["placed"], row["failed"],
        )

    async def activate_cycle_rules(self, cycle_id: int) -> None:
        await self._pool.execute(
            "UPDATE close_rules SET status = 'active' WHERE cycle_id = $1 AND status = 'pending_activation'",
            cycle_id,
        )

    async def expire_cycle_rules(self, cycle_id: int) -> None:
        await self._pool.execute(
            "UPDATE close_rules SET status = 'expired', updated_at = now() WHERE cycle_id = $1 AND status IN ('active', 'pending_activation')",
            cycle_id,
        )

    async def get_cycle_trade_symbols(self, cycle_id: int) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT DISTINCT symbol FROM cycle_trades WHERE cycle_id = $1 AND status = 'filled'",
            cycle_id,
        )
        return [r["symbol"] for r in rows]
