"""
Decay detector service.

Checks rolling windows of signal_performance rows for signs of strategy decay
and fires de-duplicated alerts into the decay_alerts table.
"""

from __future__ import annotations

from typing import Any


class DecayDetector:
    """Detect strategy-decay signals and persist alerts.

    Args:
        db: Database object with a ``pool`` attribute (asyncpg pool).
    """

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------

    def __init__(self, db: Any, ws_manager: Any = None) -> None:
        self._db = db
        self._ws = ws_manager

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------

    async def check(self, new_row: dict) -> list[dict]:  # noqa: ARG002
        """Run all decay checks and return any newly created alert dicts.

        Called after each signal_performance row is materialised.

        Args:
            new_row: The freshly inserted signal_performance row (unused for
                     the rolling-window logic but kept for future per-row
                     checks).

        Returns:
            A list of alert dicts that were inserted during this call.
            Each dict contains the keys passed to ``_maybe_alert()``.
        """
        rows = await self._db.pool.fetch(
            """
            SELECT is_win,
                   confidence_score,
                   regime_at_entry,
                   realized_pnl_pct,
                   benchmark_bnh_pnl_pct
            FROM   signal_performance
            ORDER  BY closed_at DESC
            LIMIT  30
            """,
        )

        fired: list[dict] = []

        # ── win_rate_drop ──────────────────────────────────────────────────
        last_20 = rows[:20]
        if len(last_20) >= 20:
            wins_20 = sum(1 for r in last_20 if r["is_win"])
            win_rate_20 = wins_20 / len(last_20)

            if win_rate_20 < 0.30:
                alert = await self._maybe_alert(
                    alert_type="win_rate_drop",
                    severity="critical",
                    message=(
                        f"Win rate over last 20 trades is "
                        f"{win_rate_20:.1%}, below 30% critical threshold."
                    ),
                    metric_value=round(win_rate_20 * 100, 4),
                    threshold=30.0,
                    window_trades=20,
                )
                if alert:
                    fired.append(alert)
            elif win_rate_20 < 0.40:
                alert = await self._maybe_alert(
                    alert_type="win_rate_drop",
                    severity="warning",
                    message=(
                        f"Win rate over last 20 trades is "
                        f"{win_rate_20:.1%}, below 40% warning threshold."
                    ),
                    metric_value=round(win_rate_20 * 100, 4),
                    threshold=40.0,
                    window_trades=20,
                )
                if alert:
                    fired.append(alert)

        # ── losing_streak ─────────────────────────────────────────────────
        streak = 0
        for r in rows:
            if not r["is_win"]:
                streak += 1
            else:
                break

        if streak >= 8:
            alert = await self._maybe_alert(
                alert_type="losing_streak",
                severity="critical",
                message=(
                    f"Losing streak of {streak} consecutive trades "
                    f"exceeds critical threshold of 8."
                ),
                metric_value=float(streak),
                threshold=8.0,
                window_trades=streak,
            )
            if alert:
                fired.append(alert)
        elif streak >= 5:
            alert = await self._maybe_alert(
                alert_type="losing_streak",
                severity="warning",
                message=(
                    f"Losing streak of {streak} consecutive trades "
                    f"exceeds warning threshold of 5."
                ),
                metric_value=float(streak),
                threshold=5.0,
                window_trades=streak,
            )
            if alert:
                fired.append(alert)

        # ── confidence_miscalibration ──────────────────────────────────────
        high_conf = [r for r in rows if (r["confidence_score"] or 0) >= 7]
        if len(high_conf) >= 10:
            wins_hc = sum(1 for r in high_conf if r["is_win"])
            win_rate_hc = wins_hc / len(high_conf)
            if win_rate_hc < 0.50:
                alert = await self._maybe_alert(
                    alert_type="confidence_miscalibration",
                    severity="warning",
                    message=(
                        f"High-confidence trades (score ≥ 7) win rate is "
                        f"{win_rate_hc:.1%}, below 50% threshold "
                        f"({len(high_conf)} qualifying trades)."
                    ),
                    metric_value=round(win_rate_hc * 100, 4),
                    threshold=50.0,
                    window_trades=len(high_conf),
                )
                if alert:
                    fired.append(alert)

        # ── negative_alpha ────────────────────────────────────────────────
        if len(rows) >= 20:
            total_pnl = sum(
                float(r["realized_pnl_pct"] or 0) for r in rows
            )
            total_bnh = sum(
                float(r["benchmark_bnh_pnl_pct"] or 0) for r in rows
            )
            if total_pnl < total_bnh:
                alert = await self._maybe_alert(
                    alert_type="negative_alpha",
                    severity="warning",
                    message=(
                        f"Cumulative PnL ({total_pnl:.2f}%) is below "
                        f"buy-and-hold benchmark ({total_bnh:.2f}%) "
                        f"over last {len(rows)} trades."
                    ),
                    metric_value=round(total_pnl - total_bnh, 4),
                    threshold=0.0,
                    window_trades=len(rows),
                )
                if alert:
                    fired.append(alert)

        return fired

    # --------------------------------------------------------------------------
    # Internal helpers
    # --------------------------------------------------------------------------

    async def _maybe_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        message: str,
        metric_value: float,
        threshold: float,
        window_trades: int,
    ) -> dict | None:
        """Insert an alert only if no unacknowledged duplicate exists.

        Args:
            alert_type: One of the defined alert type strings.
            severity: ``"warning"`` or ``"critical"``.
            message: Human-readable description of the alert.
            metric_value: The measured value that triggered the alert.
            threshold: The threshold that was breached.
            window_trades: Number of trades in the rolling window examined.

        Returns:
            The alert dict if a new row was inserted, or ``None`` if a
            duplicate unacknowledged alert already existed.
        """
        existing = await self._db.pool.fetchrow(
            "SELECT id FROM decay_alerts WHERE alert_type = $1 AND acknowledged = FALSE",
            alert_type,
        )
        if existing:
            return None

        await self._db.pool.execute(
            """
            INSERT INTO decay_alerts
                (alert_type, severity, message, metric_value, threshold, window_trades)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            alert_type,
            severity,
            message,
            metric_value,
            threshold,
            window_trades,
        )

        if self._ws:
            try:
                await self._ws._broadcast({
                    "type": "decay_alert.fired",
                    "alert_type": alert_type,
                    "severity": severity,
                    "message": message,
                })
            except Exception:
                pass

        return {
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "metric_value": metric_value,
            "threshold": threshold,
            "window_trades": window_trades,
        }
