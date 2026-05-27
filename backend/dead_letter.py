"""Dead-letter queue — captures failed operations for inspection and retry."""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """Records failed operations in the dead_letter table for later retry."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def record_failure(
        self,
        operation: str,
        payload: dict[str, Any],
        error: Exception,
        max_retries: int = 3,
    ) -> Optional[str]:
        """Insert a failed operation into the dead-letter queue.

        Returns the DLQ entry ID, or None if recording itself fails.
        """
        try:
            error_msg = str(error)[:2000]
            tb = traceback.format_exception(type(error), error, error.__traceback__)
            stack = "".join(tb)[:10000]

            async with self._db.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO dead_letter (operation, payload, error_type, error_message, stack_trace, max_retries)
                    VALUES ($1, $2::jsonb, $3, $4, $5, $6)
                    RETURNING id::text
                    """,
                    operation,
                    json.dumps(payload, default=str),
                    type(error).__name__,
                    error_msg,
                    stack,
                    max_retries,
                )
                dlq_id = row["id"] if row else None
                logger.warning(
                    "dlq_recorded",
                    extra={"operation": operation, "dlq_id": dlq_id, "error_type": type(error).__name__},
                )
                return dlq_id
        except Exception:
            logger.exception("dlq_record_failed: could not persist to dead_letter table")
            return None

    async def get_pending(self, operation: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Retrieve pending DLQ entries for review or retry."""
        async with self._db.pool.acquire() as conn:
            if operation:
                rows = await conn.fetch(
                    "SELECT * FROM dead_letter WHERE status = 'pending' AND operation = $1 ORDER BY created_at LIMIT $2",
                    operation, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM dead_letter WHERE status = 'pending' ORDER BY created_at LIMIT $1",
                    limit,
                )
            return [dict(r) for r in rows]

    async def resolve(self, dlq_id: str, resolved_by: str = "system") -> bool:
        """Mark a DLQ entry as resolved."""
        async with self._db.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE dead_letter SET status = 'resolved', resolved_at = NOW(), resolved_by = $1 WHERE id = $2::uuid",
                resolved_by, dlq_id,
            )
            return "UPDATE 1" in result

    async def mark_exhausted(self, dlq_id: str) -> None:
        """Mark a DLQ entry as exhausted (max retries reached)."""
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE dead_letter SET status = 'exhausted' WHERE id = $1::uuid",
                dlq_id,
            )
