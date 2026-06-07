"""Pending-trade-intent records for strategy-aware orphan reconciliation (FR-051).

An MR order is placed in three steps (submit -> create_trade row -> close rule). If
the exchange order fills but the trades-row write fails, the position is an orphan
with no strategy tag. order_link_id is never sent to the exchange, so the reconciler
matches orphans by (account_id, symbol, side) — the same tuple it already uses. We
write an intent row carrying strategy_kind BEFORE submit, and delete it after a
successful create_trade; an un-deleted intent lets the reconciler recover the tag
(else quarantine — never silent 'trend').
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def write_intent(db: Any, account_id: str, symbol: str, side: str, strategy_kind: str) -> None:
    """Record a pre-submit intent. Fail-open: never block a trade on the intent write."""
    if db is None or getattr(db, "pool", None) is None:
        return
    try:
        await db.pool.execute(
            "INSERT INTO pending_trade_intents (account_id, symbol, side, strategy_kind, created_at) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (account_id, symbol, side) DO UPDATE SET "
            "strategy_kind = EXCLUDED.strategy_kind, created_at = EXCLUDED.created_at",
            account_id, symbol, side, strategy_kind, datetime.now(timezone.utc),
        )
    except Exception:
        logger.warning("pending_intent_write_failed", exc_info=True)


async def delete_intent(db: Any, account_id: str, symbol: str, side: str) -> None:
    """Remove an intent after the trade row is successfully created. Fail-open."""
    if db is None or getattr(db, "pool", None) is None:
        return
    try:
        await db.pool.execute(
            "DELETE FROM pending_trade_intents WHERE account_id=$1 AND symbol=$2 AND side=$3",
            account_id, symbol, side,
        )
    except Exception:
        logger.warning("pending_intent_delete_failed", exc_info=True)


async def lookup_strategy(db: Any, account_id: str, symbol: str, side: str) -> Optional[str]:
    """Recover the strategy_kind for an orphaned (account, symbol, side), or None."""
    if db is None or getattr(db, "pool", None) is None:
        return None
    try:
        row = await db.pool.fetchrow(
            "SELECT strategy_kind FROM pending_trade_intents "
            "WHERE account_id=$1 AND symbol=$2 AND side=$3",
            account_id, symbol, side,
        )
        return row["strategy_kind"] if row else None
    except Exception:
        logger.warning("pending_intent_lookup_failed", exc_info=True)
        return None


async def gc_stale(db: Any, max_age_minutes: int = 60) -> int:
    """Sweep unadopted intents older than max_age_minutes (rejected/never-filled). Returns count."""
    if db is None or getattr(db, "pool", None) is None:
        return 0
    try:
        result = await db.pool.execute(
            "DELETE FROM pending_trade_intents WHERE created_at < $1",
            datetime.now(timezone.utc).replace(microsecond=0) - _minutes(max_age_minutes),
        )
        # asyncpg returns "DELETE <n>"
        return int(str(result).split()[-1]) if result else 0
    except Exception:
        logger.warning("pending_intent_gc_failed", exc_info=True)
        return 0


def _minutes(n: int):
    from datetime import timedelta
    return timedelta(minutes=n)
