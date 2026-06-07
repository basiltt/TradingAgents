"""F2-long acknowledgement: server-authoritative gate for mean-reversion longs.

The f2_long_ack table is the SOLE gate; the config bool mr_long_ack_requested is
UI-intent only and ignored here. An ack is valid only if it was made at exposure
>= the account's CURRENT mr_leverage / mr_capital_pct / mr_max_trades (so raising
any of them invalidates a prior ack — re-consent required, SD28/R5-G8).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def is_long_acknowledged(accounts_service: Any, account_id: str, cfg: dict[str, Any]) -> bool:
    """True iff a fresh ack row covers the account's current MR-long exposure."""
    db = getattr(accounts_service, "_db", None) or getattr(accounts_service, "db", None)
    if db is None or getattr(db, "pool", None) is None:
        return False  # fail-closed: cannot verify => no long
    try:
        row = await db.pool.fetchrow(
            "SELECT acked_leverage, acked_capital_pct, acked_max_trades "
            "FROM f2_long_ack WHERE account_id = $1",
            account_id,
        )
    except Exception:
        logger.warning("f2_long_ack_read_failed_failing_closed", exc_info=True)
        return False
    if row is None:
        return False
    return (
        row["acked_leverage"] >= int(cfg.get("mr_leverage", 10))
        and row["acked_capital_pct"] >= float(cfg.get("mr_capital_pct", 2.0))
        and row["acked_max_trades"] >= int(cfg.get("mr_max_trades", 2))
    )


async def record_ack(db: Any, account_id: str, *, leverage: int, capital_pct: float,
                     max_trades: int, updated_by: str | None = None) -> None:
    """Upsert the ack row from the SERVER-SIDE current config snapshot (never the
    client request body — SD28). Caller passes the persisted config values."""
    await db.pool.execute(
        "INSERT INTO f2_long_ack (account_id, acked_at, acked_leverage, acked_capital_pct, acked_max_trades, updated_by) "
        "VALUES ($1, $2, $3, $4, $5, $6) "
        "ON CONFLICT (account_id) DO UPDATE SET "
        "acked_at = EXCLUDED.acked_at, acked_leverage = EXCLUDED.acked_leverage, "
        "acked_capital_pct = EXCLUDED.acked_capital_pct, acked_max_trades = EXCLUDED.acked_max_trades, "
        "updated_by = EXCLUDED.updated_by",
        account_id, datetime.now(timezone.utc), leverage, capital_pct, max_trades, updated_by,
    )
