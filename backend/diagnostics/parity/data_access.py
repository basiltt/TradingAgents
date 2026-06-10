"""Async DB reads for the parity harness (local DB, read-only)."""
from __future__ import annotations
from datetime import datetime
from typing import Any

# Reuse the production signal/kline loaders' query shape so the engine gets
# byte-identical inputs to a real backtest. Window params are datetime objects
# (asyncpg requires real datetimes for timestamptz comparisons).
_TRADES_SQL = """
    SELECT t.symbol, t.side, t.net_pnl, t.close_reason, t.entry_price, t.exit_price,
           t.scan_result_id, t.status, t.base_capital, t.opened_at, t.closed_at,
           COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
           sr.scan_id AS scan_id
    FROM trades t
    JOIN scan_results sr ON sr.id = t.scan_result_id
    JOIN scans s ON s.scan_id = sr.scan_id
    WHERE t.account_id = $1
      AND t.opened_at >= $2
      AND t.opened_at <  $3
    ORDER BY t.opened_at
"""

# Same SELECT/ORDER BY as BacktestService._load_signals "explicit" mode.
_SIGNALS_SQL = """
    SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
           COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
           ar.completed_at::timestamptz AS analysis_completed_at,
           s.scan_id, sr.signal_source, sr.analysis_price
    FROM scan_results sr
    JOIN scans s ON sr.scan_id = s.scan_id
    LEFT JOIN analysis_runs ar ON ar.run_id = sr.run_id
    WHERE s.scan_id = ANY($1)
      AND sr.status = 'completed'
      AND sr.direction IN ('buy', 'sell')
    ORDER BY signal_time, ABS(sr.score) DESC, ar.completed_at DESC NULLS LAST, sr.id
"""


class ParityDataAccess:
    """Read-only accessor for the parity harness over the LOCAL db."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def fetch_live_trades(
        self, account_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        rows = await self._db.pool.fetch(_TRADES_SQL, account_id, start, end)
        return [dict(r) for r in rows]

    async def fetch_signals(self, scan_ids: list[str]) -> list[dict[str, Any]]:
        rows = await self._db.pool.fetch(_SIGNALS_SQL, scan_ids)
        return [
            {
                "id": r["id"], "ticker": r["ticker"], "direction": r["direction"],
                "confidence": r["confidence"], "score": r["score"],
                "signal_time": r["signal_time"],
                "analysis_completed_at": r["analysis_completed_at"],
                "scan_id": r["scan_id"], "signal_source": r["signal_source"],
                "analysis_price": float(r["analysis_price"]) if r["analysis_price"] is not None else None,
            }
            for r in rows
        ]

    async def fetch_klines(
        self, kline_cache: Any, symbols: list[str], start: datetime, end: datetime,
        interval: str = "5m",
    ) -> dict[str, list[dict]]:
        import asyncio
        symbols = sorted(set(symbols))
        results = await asyncio.gather(
            *(kline_cache.get_klines(sym, interval, start, end) for sym in symbols)
        )
        return {sym: series for sym, series in zip(symbols, results)}
