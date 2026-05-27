"""AI Account Manager Repository — Phase 1 Task 1.3.

Async repository using raw asyncpg pool queries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

GENESIS_PREV_HASH = "0" * 64


class AIManagerRepository:
    def __init__(self, pool):
        self._pool = pool

    async def get_state(self, account_id: str) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM ai_manager_state WHERE account_id = $1",
                account_id,
            )
            return dict(row) if row else None

    _ALLOWED_COLUMNS = frozenset({
        "enabled", "fsm_state", "config", "circuit_breaker_count",
        "circuit_breaker_active", "circuit_breaker_half_open_used",
        "actions_today", "actions_this_hour", "max_daily_actions",
        "max_hourly_actions", "equity_at_day_start", "realized_loss_today",
        "realized_profit_today", "token_budget_used_today", "last_analysis_at", "last_action_at",
        "heartbeat_at", "counters_reset_at", "hourly_reset_at",
        "kill_switch_active", "strategy_version", "updated_at",
        "emergency_ref_equity", "emergency_cooldown_until", "emergency_closed_symbols",
    })

    async def upsert_state(self, account_id: str, **fields) -> Dict[str, Any]:
        fields["updated_at"] = datetime.now(timezone.utc)
        invalid = set(fields.keys()) - self._ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid columns for ai_manager_state: {invalid}")
        cols = list(fields.keys())
        vals = list(fields.values())
        insert_cols = ", ".join(["account_id"] + cols)
        insert_vals = ", ".join(f"${i+1}" for i in range(len(cols) + 1))
        conflict_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)

        sql = (
            f"INSERT INTO ai_manager_state ({insert_cols}) VALUES ({insert_vals}) "
            f"ON CONFLICT (account_id) DO UPDATE SET {conflict_set} "
            f"RETURNING *"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, account_id, *vals)
            return dict(row) if row else {}

    async def update_heartbeat(self, account_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_state SET heartbeat_at = NOW() WHERE account_id = $1",
                account_id,
            )

    async def get_enabled_accounts(self) -> list:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT account_id, circuit_breaker_count, circuit_breaker_active "
                "FROM ai_manager_state WHERE enabled = TRUE"
            )
            return [dict(r) for r in rows]

    async def get_stranded_decisions(self) -> list:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, timestamp, account_id FROM ai_manager_decisions "
                "WHERE execution_result IS NULL AND created_at < NOW() - interval '2 minutes'"
            )
            return [dict(r) for r in rows]

    async def insert_decision(
        self, account_id: str, decision_data: Dict[str, Any], hmac_key: str
    ) -> Tuple[int, datetime]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Advisory lock serializes all chain appends for this account (covers genesis case)
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))", account_id
                )
                prev_row = await conn.fetchrow(
                    "SELECT decision_hash FROM ai_manager_decisions "
                    "WHERE account_id = $1 ORDER BY timestamp DESC, id DESC LIMIT 1 "
                    "FOR UPDATE",
                    account_id,
                )
                prev_hash = prev_row["decision_hash"] if prev_row else GENESIS_PREV_HASH

                ts = decision_data["timestamp"]
                symbol = decision_data.get("action_taken", {}).get("symbol", "")
                decision_hash = hmac.new(
                    hmac_key.encode(),
                    "|".join([
                        prev_hash,
                        account_id,
                        ts.isoformat(),
                        decision_data["action_type"],
                        symbol,
                        f"{decision_data['confidence']:.4f}",
                    ]).encode(),
                    hashlib.sha256,
                ).hexdigest()

                row = await conn.fetchrow(
                    """INSERT INTO ai_manager_decisions
                    (account_id, timestamp, evaluation_type, urgency, state_snapshot,
                     action_taken, reasoning, confidence, graph_path, strategy_version,
                     prev_decision_hash, decision_hash, chain_key_version)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    RETURNING id, timestamp""",
                    account_id,
                    ts,
                    decision_data["evaluation_type"],
                    decision_data["urgency"],
                    json.dumps(decision_data.get("state_snapshot", {})),
                    json.dumps(decision_data["action_taken"]),
                    decision_data["reasoning"],
                    decision_data["confidence"],
                    decision_data.get("graph_path"),
                    decision_data.get("strategy_version", "default"),
                    prev_hash,
                    decision_hash,
                    decision_data.get("chain_key_version", 1),
                )
                return (row["id"], row["timestamp"])

    async def update_decision_outcome(
        self, decision_id: int, decision_timestamp: datetime, outcome: Dict[str, Any]
    ) -> None:
        outcome_label = None
        if outcome:
            pnl_val = outcome.get("realized_pnl")
            if pnl_val is None:
                pnl_val = outcome.get("pnl_pct")
            if pnl_val is None:
                pnl_val = 0.0
            pnl = pnl_val
            if pnl > 0.5:
                outcome_label = "profitable"
            elif pnl < -0.5:
                outcome_label = "loss"
            else:
                outcome_label = "neutral"

        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_decisions SET outcome = $1, outcome_label = $2, "
                "execution_result = $3 WHERE id = $4 AND timestamp = $5",
                json.dumps(outcome) if outcome is not None else None,
                outcome_label,
                json.dumps(outcome.get("execution_result")) if outcome and outcome.get("execution_result") is not None else None,
                decision_id,
                decision_timestamp,
            )

    async def get_recent_decisions(
        self, account_id: str, limit: int = 15
    ) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, account_id, timestamp, action_taken, confidence, outcome_label "
                "FROM ai_manager_decisions "
                "WHERE account_id = $1 ORDER BY timestamp DESC LIMIT $2",
                account_id,
                limit,
            )
            return [dict(r) for r in rows]

    async def count_decisions(self, account_id: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM ai_manager_decisions WHERE account_id = $1",
                account_id,
            )
            return row["cnt"] if row else 0

    async def get_decisions_page(
        self,
        account_id: str,
        cursor_ts: Optional[datetime],
        cursor_id: Optional[int],
        limit: int = 50,
        outcome_filter: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        conditions = ["account_id = $1"]
        params: list = [account_id]
        idx = 2

        if cursor_ts and cursor_id:
            conditions.append(f"(timestamp, id) < (${idx}, ${idx+1})")
            params.extend([cursor_ts, cursor_id])
            idx += 2

        if outcome_filter:
            conditions.append(f"outcome_label = ${idx}")
            params.append(outcome_filter)
            idx += 1

        params.append(limit + 1)
        where = " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, account_id, timestamp, evaluation_type, urgency, "
                f"action_taken, reasoning, confidence, graph_path, strategy_version, "
                f"outcome, outcome_label, execution_result, prev_decision_hash, decision_hash "
                f"FROM ai_manager_decisions WHERE {where} "
                f"ORDER BY timestamp DESC, id DESC LIMIT ${idx}",
                *params,
            )

        results = [dict(r) for r in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = results[-1]
            next_cursor = f"{last['timestamp'].isoformat()}_{last['id']}"

        return (results, next_cursor)

    async def get_patterns(
        self, account_id: str, active: bool = True, limit: int = 5
    ) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ai_manager_patterns "
                "WHERE account_id = $1 AND active = $2 "
                "ORDER BY confidence DESC LIMIT $3",
                account_id,
                active,
                limit,
            )
            return [dict(r) for r in rows]

    async def upsert_pattern(
        self, account_id: str, pattern_data: Dict[str, Any]
    ) -> int:
        symbol = pattern_data.get("symbol") or ""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO ai_manager_patterns
                (account_id, pattern_type, symbol, description, confidence)
                VALUES ($1, $2, NULLIF($3, ''), $4, $5)
                ON CONFLICT (account_id, pattern_type, COALESCE(symbol, '')) WHERE active = TRUE
                DO UPDATE SET confidence = EXCLUDED.confidence, evidence_count = ai_manager_patterns.evidence_count + 1, updated_at = NOW()
                RETURNING id""",
                account_id,
                pattern_data["pattern_type"],
                symbol,
                pattern_data["description"][:200],
                pattern_data.get("confidence", 0.5),
            )
            return row["id"] if row else 0

    async def count_active_patterns(self, account_id: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM ai_manager_patterns "
                "WHERE account_id = $1 AND active = TRUE",
                account_id,
            )
            return row["cnt"]

    async def deactivate_lowest_confidence_pattern(self, account_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_patterns SET active = FALSE, updated_at = NOW() "
                "WHERE id = (SELECT id FROM ai_manager_patterns "
                "WHERE account_id = $1 AND active = TRUE "
                "ORDER BY confidence ASC LIMIT 1)",
                account_id,
            )

    async def increment_actions_atomic(self, account_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE ai_manager_state "
                "SET actions_today = actions_today + 1, "
                "    actions_this_hour = actions_this_hour + 1, "
                "    updated_at = NOW() "
                "WHERE account_id = $1 "
                "  AND actions_today < max_daily_actions "
                "  AND actions_this_hour < max_hourly_actions "
                "RETURNING account_id",
                account_id,
            )
            return row is not None

    async def record_realized_loss(
        self, account_id: str, loss_amount: float
    ) -> Dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE ai_manager_state "
                "SET realized_loss_today = realized_loss_today + $2, updated_at = NOW() "
                "WHERE account_id = $1 "
                "RETURNING realized_loss_today, equity_at_day_start",
                account_id,
                loss_amount,
            )
            return dict(row) if row else {}

    async def init_equity_at_day_start(self, account_id: str, equity: float) -> None:
        """Atomically set equity_at_day_start only if NULL (first writer wins)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_state "
                "SET equity_at_day_start = $2, updated_at = NOW() "
                "WHERE account_id = $1 AND equity_at_day_start IS NULL",
                account_id,
                equity,
            )

    async def record_realized_profit(
        self, account_id: str, profit_amount: float
    ) -> Dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE ai_manager_state "
                "SET realized_profit_today = COALESCE(realized_profit_today, 0) + $2, updated_at = NOW() "
                "WHERE account_id = $1 "
                "RETURNING realized_profit_today, equity_at_day_start",
                account_id,
                profit_amount,
            )
            return dict(row) if row else {}

    async def increment_token_budget_atomic(
        self, account_id: str, tokens_used: int, max_tokens: int
    ) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE ai_manager_state "
                "SET token_budget_used_today = token_budget_used_today + $2 "
                "WHERE account_id = $1 "
                "  AND token_budget_used_today + $2 <= $3 "
                "RETURNING account_id",
                account_id,
                tokens_used,
                max_tokens,
            )
            return row is not None

    async def is_kill_switch_active(self, account_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT kill_switch_active FROM ai_manager_state WHERE account_id = $1",
                account_id,
            )
            return bool(row and row["kill_switch_active"])

    async def set_kill_switch(self, account_id: str, active: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_state SET kill_switch_active = $2, updated_at = NOW() "
                "WHERE account_id = $1",
                account_id,
                active,
            )

    async def set_global_kill(self, active: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_state SET kill_switch_active = $1, updated_at = NOW() "
                "WHERE enabled = TRUE",
                active,
            )

    async def reset_kill_switch(self, account_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_state SET kill_switch_active = FALSE, updated_at = NOW() "
                "WHERE account_id = $1",
                account_id,
            )

    async def sync_config_columns(
        self, account_id: str, config: Dict[str, Any]
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_state "
                "SET config = $2, max_daily_actions = $3, max_hourly_actions = $4, updated_at = NOW() "
                "WHERE account_id = $1",
                account_id,
                json.dumps(config),
                config.get("max_daily_actions", 30),
                config.get("max_hourly_actions", 10),
            )

    # Dead-letter operations

    async def insert_failed_outcome(
        self, decision_id: int, decision_timestamp: datetime, result: Dict, reason: str
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO ai_manager_failed_outcomes "
                "(decision_id, decision_timestamp, execution_result, failure_reason, next_retry_at) "
                "VALUES ($1, $2, $3, $4, NOW() + interval '30 seconds') "
                "RETURNING id",
                decision_id,
                decision_timestamp,
                json.dumps(result),
                reason,
            )
            return row["id"]

    async def get_pending_retries(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ai_manager_failed_outcomes "
                "WHERE resolved = FALSE AND next_retry_at <= NOW() "
                "ORDER BY next_retry_at LIMIT $1",
                limit,
            )
            return [dict(r) for r in rows]

    async def increment_retry(self, failed_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_failed_outcomes "
                "SET retry_count = retry_count + 1, "
                "    next_retry_at = NOW() + (interval '30 seconds' * power(2, retry_count)) "
                "WHERE id = $1 AND retry_count < max_retries",
                failed_id,
            )

    async def mark_resolved(self, failed_id: int, reason: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_failed_outcomes "
                "SET resolved = TRUE, failure_reason = failure_reason || ' | resolved: ' || $2 "
                "WHERE id = $1",
                failed_id,
                reason,
            )

    # Global state

    async def get_degradation_tier(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT int_value FROM ai_manager_global_state WHERE key = 'degradation_tier'"
            )
            return row["int_value"] if row else 0

    async def set_degradation_tier(self, tier: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_manager_global_state SET int_value = $1, updated_at = NOW() "
                "WHERE key = 'degradation_tier'",
                tier,
            )

    async def generate_patterns_locked(self, account_id: str, callback) -> int:
        """Execute pattern generation with advisory lock held on a single connection.
        Callback receives (account_id, conn) — must use the provided connection for all DB ops.
        """
        import hashlib
        lock_key = int(hashlib.md5(f"{account_id}:7001".encode()).hexdigest(), 16) % (2**31)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT pg_try_advisory_lock($1) AS acquired", lock_key
            )
            if not (row and row["acquired"]):
                return 0
            try:
                return await callback(account_id, conn)
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)

    async def insert_pattern(
        self,
        account_id: str,
        pattern_type: str,
        symbol: str,
        description: str,
        confidence: float,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO ai_manager_patterns "
                "(account_id, pattern_type, symbol, description, confidence, active) "
                "VALUES ($1, $2, $3, $4, $5, TRUE)",
                account_id,
                pattern_type,
                symbol,
                description,
                confidence,
            )

    async def get_performance_metrics(self, account_id: str, period: str = "7d") -> Dict[str, Any]:
        days = {"1d": 1, "7d": 7, "30d": 30}.get(period, 7)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT "
                "  COUNT(*) AS total_decisions, "
                "  COUNT(*) FILTER (WHERE outcome_label = 'profitable') AS wins, "
                "  COUNT(*) FILTER (WHERE outcome_label = 'loss') AS losses, "
                "  COALESCE(SUM((execution_result->>'realized_pnl')::numeric) FILTER (WHERE outcome_label = 'profitable'), 0) AS gross_profit, "
                "  COALESCE(SUM(ABS((execution_result->>'realized_pnl')::numeric)) FILTER (WHERE outcome_label = 'loss'), 0) AS gross_loss "
                "FROM ai_manager_decisions "
                "WHERE account_id = $1 AND timestamp > NOW() - ($2 || ' days')::interval",
                account_id, str(days),
            )
        total = row["total_decisions"]
        wins = row["wins"]
        losses = row["losses"]
        gross_profit = float(row["gross_profit"])
        gross_loss = float(row["gross_loss"])
        return {
            "period": period,
            "total_decisions": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total, 4) if total > 0 else 0.0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "net_pnl": round(gross_profit - gross_loss, 8),
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        }

    # ─── Logs ──────────────────────────────────────────────────────────────

    async def insert_log(
        self,
        account_id: str,
        level: str,
        category: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a structured log entry for an AI-managed account."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO ai_manager_logs (account_id, level, category, message, details)
                       VALUES ($1, $2, $3, $4, $5::jsonb)""",
                    account_id,
                    level,
                    category,
                    message,
                    json.dumps(details) if details else None,
                )
                # Probabilistic retention: ~2% of inserts trigger cleanup to cap at 1000 rows/account
                if random.random() < 0.02:
                    await conn.execute(
                        """DELETE FROM ai_manager_logs WHERE account_id = $1 AND id NOT IN (
                            SELECT id FROM ai_manager_logs WHERE account_id = $1 ORDER BY id DESC LIMIT 1000
                        )""",
                        account_id,
                    )
        except Exception:
            logger.debug("Failed to insert AI manager log for %s", account_id)

    async def get_logs(
        self,
        account_id: str,
        limit: int = 100,
        level_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        cursor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get paginated logs for an account, newest first."""
        conditions = ["account_id = $1"]
        params: list = [account_id]
        idx = 2

        if level_filter:
            conditions.append(f"level = ${idx}")
            params.append(level_filter)
            idx += 1

        if category_filter:
            conditions.append(f"category = ${idx}")
            params.append(category_filter)
            idx += 1

        if cursor_id:
            conditions.append(f"id < ${idx}")
            params.append(cursor_id)
            idx += 1

        where = " AND ".join(conditions)
        params.append(limit + 1)

        async with self._pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    f"SELECT id, timestamp, level, category, message, details FROM ai_manager_logs WHERE {where} ORDER BY id DESC LIMIT ${idx}",
                    *params,
                )
            except Exception as e:
                if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
                    return {"logs": [], "next_cursor": None}
                raise

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1]["id"] if has_more and items else None

        return {
            "logs": [
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    "level": r["level"],
                    "category": r["category"],
                    "message": r["message"],
                    "details": (json.loads(r["details"]) if isinstance(r["details"], str) else r["details"]) if r["details"] else None,
                }
                for r in items
            ],
            "next_cursor": next_cursor,
        }

    # ─── Enhanced AI Manager persistence ──────────────────────────────────

    async def get_sweep_state(self, account_id: str) -> Dict[str, Any]:
        row = await self._pool.fetchrow(
            "SELECT sweep_state FROM ai_manager_state WHERE account_id = $1",
            account_id,
        )
        if row and row["sweep_state"]:
            return json.loads(row["sweep_state"]) if isinstance(row["sweep_state"], str) else row["sweep_state"]
        return {}

    async def update_sweep_state(self, account_id: str, sweep_state: Dict[str, Any]) -> None:
        await self._pool.execute(
            "UPDATE ai_manager_state SET sweep_state = $2::jsonb, updated_at = NOW() WHERE account_id = $1",
            account_id, json.dumps(sweep_state),
        )

    async def insert_regime_history(
        self, account_id: str, symbol: str, regime: str, confidence: float, detail: Dict[str, Any]
    ) -> None:
        await self._pool.execute(
            "INSERT INTO ai_manager_regime_history (account_id, symbol, regime, confidence, detail) VALUES ($1, $2, $3, $4, $5::jsonb)",
            account_id, symbol, regime, confidence, json.dumps(detail),
        )

    async def insert_correlation_snapshot(
        self, account_id: str, portfolio_heat: float, matrix: Dict, clusters: list, position_count: int
    ) -> None:
        await self._pool.execute(
            "INSERT INTO ai_manager_correlation_snapshots (account_id, portfolio_heat, matrix, clusters, position_count) VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)",
            account_id, portfolio_heat, json.dumps(matrix), json.dumps(clusters), position_count,
        )

    async def insert_sweep_event(self, account_id: str, **kwargs) -> None:
        detail = kwargs.pop("detail", None)
        cols = ["account_id"] + list(kwargs.keys())
        if detail is not None:
            cols.append("detail")
        vals = [account_id] + list(kwargs.values())
        if detail is not None:
            vals.append(json.dumps(detail))
        placeholders = ", ".join(f"${i+1}" for i in range(len(vals)))
        col_str = ", ".join(cols)
        await self._pool.execute(
            f"INSERT INTO ai_manager_sweep_events ({col_str}) VALUES ({placeholders})",
            *vals,
        )

    async def insert_orderbook_snapshot(
        self, account_id: str, symbol: str, imbalance_ratio: float, spread_bps: float,
        depth_ratio: float, bid_clusters: list, ask_clusters: list, spoofing_flags: list = None,
    ) -> None:
        await self._pool.execute(
            "INSERT INTO ai_manager_orderbook_snapshots (account_id, symbol, imbalance_ratio, spread_bps, depth_ratio, bid_clusters, ask_clusters, spoofing_flags) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb)",
            account_id, symbol, imbalance_ratio, spread_bps, depth_ratio,
            json.dumps(bid_clusters), json.dumps(ask_clusters), json.dumps(spoofing_flags or []),
        )

    async def cleanup_old_data(self) -> None:
        """Retention cleanup — call from a periodic task."""
        await self._pool.execute(
            "DELETE FROM ai_manager_orderbook_snapshots WHERE created_at < NOW() - INTERVAL '24 hours'"
        )
        await self._pool.execute(
            "DELETE FROM ai_manager_correlation_snapshots WHERE created_at < NOW() - INTERVAL '7 days'"
        )
        await self._pool.execute(
            "DELETE FROM ai_manager_regime_history WHERE created_at < NOW() - INTERVAL '30 days'"
        )
        await self._pool.execute(
            "DELETE FROM ai_manager_sweep_events WHERE created_at < NOW() - INTERVAL '90 days'"
        )
