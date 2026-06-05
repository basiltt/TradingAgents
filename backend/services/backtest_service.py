"""Backtest Service — orchestrates backtest lifecycle.

Handles: create, run, cancel, list, compare, delete.
Delegates simulation to BacktestEngine (pure, synchronous).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BacktestService:
    """Orchestration service for backtesting.

    Args:
        db: AsyncAnalysisDB instance with pool attribute.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def _load_signals(
        self,
        scan_source: dict[str, Any],
        date_range: tuple[datetime, datetime],
    ) -> list[dict[str, Any]]:
        """Load historical scan result signals for the backtest engine.

        Supports 3 modes:
        - "schedule": Load all scan results from a specific scheduled scanner
        - "date_range": Load all scan results within date range (any scanner)
        - "explicit": Load scan results from specific scan IDs

        The query JOINs scan_results with scans to get signal timestamps,
        since scan_results has no timestamp column itself.

        Returns:
            List of signal dicts with: id, ticker, direction, confidence,
            score, signal_time, scan_id, signal_source.
        """
        mode = scan_source.get("mode", "date_range")
        start, end = date_range

        if mode == "schedule":
            schedule_id = scan_source.get("schedule_id")
            query = """
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       s.started_at::timestamptz AS signal_time,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                WHERE s.schedule_id = $1
                  AND s.started_at::timestamptz >= $2
                  AND s.started_at::timestamptz <= $3
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY s.started_at::timestamptz, ABS(sr.score) DESC
            """
            rows = await self._db.pool.fetch(query, schedule_id, start, end)

        elif mode == "explicit":
            scan_ids = scan_source.get("scan_ids", [])
            query = """
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       s.started_at::timestamptz AS signal_time,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                WHERE s.scan_id = ANY($1)
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY s.started_at::timestamptz, ABS(sr.score) DESC
            """
            rows = await self._db.pool.fetch(query, scan_ids)

        else:  # date_range (default)
            query = """
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       s.started_at::timestamptz AS signal_time,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                WHERE s.started_at::timestamptz >= $1
                  AND s.started_at::timestamptz <= $2
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY s.started_at::timestamptz, ABS(sr.score) DESC
            """
            rows = await self._db.pool.fetch(query, start, end)

        # Convert asyncpg Records to plain dicts
        signals = []
        for row in rows:
            signals.append({
                "id": row["id"],
                "ticker": row["ticker"],
                "direction": row["direction"],
                "confidence": row["confidence"],
                "score": row["score"],
                "signal_time": row["signal_time"],
                "scan_id": row["scan_id"],
                "signal_source": row.get("signal_source", "unknown"),
                "analysis_price": float(row["analysis_price"]) if row.get("analysis_price") else None,
            })

        logger.info(
            "backtest_signals_loaded",
            extra={"mode": mode, "count": len(signals), "date_range": f"{start} to {end}"},
        )
        return signals
