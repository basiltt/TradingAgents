"""SignalAnalyticsService — query layer for signal-performance dashboard data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class SignalAnalyticsService:
    """Provides all read (and lightweight write) queries for the signal analytics dashboard.

    Args:
        db: AsyncAnalysisDB instance exposing a ``pool`` attribute backed by asyncpg.
    """

    def __init__(self, db) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _default_dates(
        self,
        start_date: str | None,
        end_date: str | None,
    ) -> tuple[str, str]:
        """Return (start_date, end_date) defaulting to the last 90 days."""
        if start_date and end_date:
            return start_date, end_date
        today = datetime.now(timezone.utc).date()
        return str(today - timedelta(days=90)), str(today)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_summary(
        self,
        account_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Return high-level KPIs for the dashboard header cards.

        Args:
            account_id: Optional UUID string to scope results to one account.
            start_date: ISO date string (YYYY-MM-DD).  Defaults to 90 days ago.
            end_date: ISO date string (YYYY-MM-DD).  Defaults to today.

        Returns:
            Dict with keys: total_trades, win_rate, avg_pnl_pct, total_pnl,
            avg_hold_minutes, current_streak, active_alerts.
        """
        sd, ed = self._default_dates(start_date, end_date)

        where_parts = ["closed_at::date >= $1", "closed_at::date <= $2"]
        params: list[Any] = [sd, ed]

        if account_id is not None:
            params.append(account_id)
            where_parts.append(f"account_id = ${len(params)}")

        where = " AND ".join(where_parts)

        agg_row = await self._db.pool.fetchrow(
            f"""
            SELECT
                COUNT(*)                          AS total_trades,
                COALESCE(SUM(is_win::int), 0)     AS win_count,
                AVG(realized_pnl_pct)             AS avg_pnl_pct,
                COALESCE(SUM(net_pnl), 0)         AS total_pnl,
                AVG(hold_duration_minutes)        AS avg_hold_minutes
            FROM signal_performance
            WHERE {where}
            """,
            *params,
        )

        total = int(agg_row["total_trades"] or 0)
        win_count = int(agg_row["win_count"] or 0)
        win_rate = (win_count / total) if total > 0 else 0.0
        avg_pnl_pct = float(agg_row["avg_pnl_pct"] or 0.0)
        total_pnl = float(agg_row["total_pnl"] or 0.0)
        avg_hold_minutes = float(agg_row["avg_hold_minutes"] or 0.0)

        # Current streak — look at last 50 trades regardless of date filter
        streak_where_parts = []
        streak_params: list[Any] = []
        if account_id is not None:
            streak_params.append(account_id)
            streak_where_parts.append(f"account_id = ${len(streak_params)}")

        streak_where = f"WHERE {' AND '.join(streak_where_parts)}" if streak_where_parts else ""
        recent_rows = await self._db.pool.fetch(
            f"""
            SELECT is_win
            FROM signal_performance
            {streak_where}
            ORDER BY closed_at DESC
            LIMIT 50
            """,
            *streak_params,
        )

        current_streak = ""
        if recent_rows:
            first = bool(recent_rows[0]["is_win"])
            count = 0
            for row in recent_rows:
                if bool(row["is_win"]) == first:
                    count += 1
                else:
                    break
            current_streak = f"{count}{'W' if first else 'L'}"

        # Active alert count
        alert_count = await self._db.pool.fetchval(
            "SELECT COUNT(*) FROM decay_alerts WHERE acknowledged = FALSE"
        )

        return {
            "total_trades": total,
            "win_rate": win_rate,
            "avg_pnl_pct": avg_pnl_pct,
            "total_pnl": total_pnl,
            "avg_hold_minutes": avg_hold_minutes,
            "current_streak": current_streak,
            "active_alerts": int(alert_count or 0),
        }

    async def get_rolling_win_rate(
        self,
        account_id: str | None = None,
        window: int = 20,
    ) -> list[dict]:
        """Compute a rolling win-rate series for charting.

        Args:
            account_id: Optional account scope.
            window: Rolling window size (number of trades).

        Returns:
            List of dicts with keys: date, win_rate, trade_number.
        """
        where_parts: list[str] = []
        params: list[Any] = []

        if account_id is not None:
            params.append(account_id)
            where_parts.append(f"account_id = ${len(params)}")

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        rows = await self._db.pool.fetch(
            f"""
            SELECT closed_at, is_win
            FROM signal_performance
            {where}
            ORDER BY closed_at ASC
            """,
            *params,
        )

        result: list[dict] = []
        wins_window: list[bool] = []
        for i, row in enumerate(rows):
            wins_window.append(bool(row["is_win"]))
            if len(wins_window) > window:
                wins_window.pop(0)
            if len(wins_window) >= window:
                wr = sum(wins_window) / window
                result.append({
                    "date": row["closed_at"].isoformat() if row["closed_at"] else None,
                    "win_rate": wr,
                    "trade_number": i + 1,
                })

        return result

    async def get_calibration_curve(
        self,
        account_id: str | None = None,
    ) -> list[dict]:
        """Return win rate per confidence tier for calibration chart.

        Args:
            account_id: Optional account scope.

        Returns:
            List of dicts: {tier, total, wins, win_rate}.
        """
        where_parts: list[str] = []
        params: list[Any] = []

        if account_id is not None:
            params.append(account_id)
            where_parts.append(f"account_id = ${len(params)}")

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        rows = await self._db.pool.fetch(
            f"""
            SELECT
                confidence_tier                    AS tier,
                COUNT(*)                           AS total,
                COALESCE(SUM(is_win::int), 0)      AS wins
            FROM signal_performance
            {where}
            GROUP BY confidence_tier
            ORDER BY confidence_tier
            """,
            *params,
        )

        result: list[dict] = []
        for row in rows:
            total = int(row["total"] or 0)
            wins = int(row["wins"] or 0)
            result.append({
                "tier": row["tier"],
                "total": total,
                "wins": wins,
                "win_rate": (wins / total) if total > 0 else 0.0,
            })
        return result

    async def get_benchmark_comparison(
        self,
        account_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """Cumulative PnL curves for the system, buy-and-hold, and random-entry benchmarks.

        Args:
            account_id: Optional account scope.
            start_date: ISO date string.  Defaults to 90 days ago.
            end_date: ISO date string.  Defaults to today.

        Returns:
            List of dicts: {date, trade_number, system_pnl, buy_and_hold, random_expected}.
        """
        sd, ed = self._default_dates(start_date, end_date)

        where_parts = ["closed_at::date >= $1", "closed_at::date <= $2"]
        params: list[Any] = [sd, ed]

        if account_id is not None:
            params.append(account_id)
            where_parts.append(f"account_id = ${len(params)}")

        where = " AND ".join(where_parts)

        rows = await self._db.pool.fetch(
            f"""
            SELECT closed_at, realized_pnl_pct, benchmark_bnh_pnl_pct, benchmark_random_expected_pnl
            FROM signal_performance
            WHERE {where}
            ORDER BY closed_at ASC
            """,
            *params,
        )

        result: list[dict] = []
        cum_system = 0.0
        cum_bnh = 0.0
        cum_random = 0.0
        for i, row in enumerate(rows):
            cum_system += float(row["realized_pnl_pct"] or 0.0)
            cum_bnh += float(row["benchmark_bnh_pnl_pct"] or 0.0)
            cum_random += float(row["benchmark_random_expected_pnl"] or 0.0)
            result.append({
                "date": row["closed_at"].isoformat() if row["closed_at"] else None,
                "trade_number": i + 1,
                "system_pnl": cum_system,
                "buy_and_hold": cum_bnh,
                "random_expected": cum_random,
            })
        return result

    async def get_regime_breakdown(
        self,
        account_id: str | None = None,
    ) -> list[dict]:
        """Win rate and average PnL grouped by market regime.

        Args:
            account_id: Optional account scope.

        Returns:
            List of dicts: {regime, total, wins, win_rate, avg_pnl_pct}.
        """
        where_parts: list[str] = []
        params: list[Any] = []

        if account_id is not None:
            params.append(account_id)
            where_parts.append(f"account_id = ${len(params)}")

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        rows = await self._db.pool.fetch(
            f"""
            SELECT
                regime_at_entry                    AS regime,
                COUNT(*)                           AS total,
                COALESCE(SUM(is_win::int), 0)      AS wins,
                AVG(realized_pnl_pct)              AS avg_pnl_pct
            FROM signal_performance
            {where}
            GROUP BY regime_at_entry
            ORDER BY regime_at_entry
            """,
            *params,
        )

        result: list[dict] = []
        for row in rows:
            total = int(row["total"] or 0)
            wins = int(row["wins"] or 0)
            result.append({
                "regime": row["regime"],
                "total": total,
                "wins": wins,
                "win_rate": (wins / total) if total > 0 else 0.0,
                "avg_pnl_pct": float(row["avg_pnl_pct"] or 0.0),
            })
        return result

    async def get_current_regimes(self) -> list[dict]:
        """Fetch the most recent regime snapshot for each symbol.

        Returns:
            List of dicts representing the latest regime_snapshots row per symbol.
        """
        rows = await self._db.pool.fetch(
            """
            SELECT DISTINCT ON (symbol)
                id, symbol, regime, adx, atr_pct, bb_width_pct,
                llm_confirmed, llm_regime, classified_at
            FROM regime_snapshots
            ORDER BY symbol, classified_at DESC
            """
        )
        return [dict(row) for row in rows]

    async def get_decay_alerts(self, acknowledged: bool = False) -> list[dict]:
        """Fetch decay alerts filtered by acknowledgement status.

        Args:
            acknowledged: When False (default) return only unacknowledged alerts.

        Returns:
            List of dicts representing decay_alerts rows.
        """
        rows = await self._db.pool.fetch(
            """
            SELECT id, alert_type, severity, message, metric_value, threshold,
                   window_trades, acknowledged, created_at
            FROM decay_alerts
            WHERE acknowledged = $1
            ORDER BY created_at DESC
            """,
            acknowledged,
        )
        return [dict(row) for row in rows]

    async def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark a decay alert as acknowledged.

        Args:
            alert_id: Primary key of the alert to acknowledge.

        Returns:
            True if the row was found and updated, False otherwise.
        """
        result = await self._db.pool.execute(
            "UPDATE decay_alerts SET acknowledged = TRUE WHERE id = $1",
            alert_id,
        )
        # asyncpg returns a string like "UPDATE 1"
        return result == "UPDATE 1"

    async def get_performance_trades(
        self,
        account_id: str | None = None,
        symbol: str | None = None,
        confidence_tier: str | None = None,
        regime: str | None = None,
        is_win: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Paginated list of signal_performance rows with optional filters.

        Args:
            account_id: Filter by account UUID string.
            symbol: Filter by trading symbol (e.g. "BTCUSDT").
            confidence_tier: Filter by confidence tier label.
            regime: Filter by regime_at_entry value.
            is_win: Filter by win/loss outcome.
            limit: Maximum rows to return (caller should cap at 200).
            offset: Pagination offset.

        Returns:
            Dict with keys: total (int), trades (list[dict]).
        """
        where_parts: list[str] = []
        params: list[Any] = []

        def _add(clause_template: str, value: Any) -> None:
            params.append(value)
            where_parts.append(clause_template.replace("?", f"${len(params)}"))

        if account_id is not None:
            _add("account_id = ?", account_id)
        if symbol is not None:
            _add("symbol = ?", symbol)
        if confidence_tier is not None:
            _add("confidence_tier = ?", confidence_tier)
        if regime is not None:
            _add("regime_at_entry = ?", regime)
        if is_win is not None:
            _add("is_win = ?", is_win)

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        count_row = await self._db.pool.fetchval(
            f"SELECT COUNT(*) FROM signal_performance {where}",
            *params,
        )
        total = int(count_row or 0)

        params.append(limit)
        params.append(offset)
        rows = await self._db.pool.fetch(
            f"""
            SELECT *
            FROM signal_performance
            {where}
            ORDER BY closed_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )

        trades = [dict(row) for row in rows]
        return {"total": total, "trades": trades}
