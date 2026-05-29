"""SignalPerformanceMaterializer — persists per-trade signal performance rows.

For each closed trade that originated from a scanner signal, this service
computes benchmark comparisons (buy-and-hold, random entry) and writes a
``signal_performance`` record.  An optional ``decay_detector`` hook is called
after every successful insert so downstream models can flag degrading signals
in real time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def compute_random_expected_pnl(tp_pct: float, sl_pct: float) -> float:
    """Compute the expected PnL for a random entry with fixed TP/SL levels.

    Uses the closed-form formula derived from equal-probability random-walk
    hitting-time theory:

        P(win) = sl_pct / (tp_pct + sl_pct)
        E[PnL] = P(win) * tp_pct - (1 - P(win)) * sl_pct

    Args:
        tp_pct: Take-profit distance in percent (must be > 0).
        sl_pct: Stop-loss distance in percent (must be > 0).

    Returns:
        Expected PnL percentage, or 0.0 if either argument is non-positive.
    """
    if tp_pct <= 0 or sl_pct <= 0:
        return 0.0
    p_win = sl_pct / (tp_pct + sl_pct)
    return p_win * tp_pct - (1.0 - p_win) * sl_pct


def _score_to_tier(score: int) -> str:
    """Map an absolute scan score to a human-readable confidence tier.

    Args:
        score: Absolute value of the raw scanner score (0–10 range expected).

    Returns:
        One of ``"high"``, ``"moderate"``, or ``"low"``.
    """
    abs_score = abs(score)
    if abs_score >= 7:
        return "high"
    if abs_score >= 4:
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------

class SignalPerformanceMaterializer:
    """Computes and persists a ``signal_performance`` row for a closed trade.

    Args:
        db: Database access object exposing an asyncpg ``pool`` attribute.
        decay_detector: Optional object with an async ``check(row)`` method
            called after every successful insert.  Exceptions from this hook
            are caught and logged rather than propagated.
    """

    def __init__(self, db: Any, decay_detector: Any = None) -> None:
        self._db = db
        self._decay = decay_detector

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def materialize(self, trade: dict) -> dict | None:
        """Compute metrics and insert a ``signal_performance`` row.

        Args:
            trade: A dict representing a closed trade record.  Required keys:
                ``id``, ``symbol``, ``signal_direction``, ``entry_price``,
                ``exit_price``, ``opened_at``, ``closed_at``, ``net_pnl``,
                ``take_profit_pct``, ``stop_loss_pct``, ``scan_result_id``.
                ``fees`` and ``close_reason`` are optional.

        Returns:
            A dict containing all inserted column values, or ``None`` when the
            trade should be skipped (missing ``scan_result_id`` or
            ``exit_price``, or scan_result row not found in the DB).
        """
        if not trade.get("scan_result_id"):
            return None
        if trade.get("exit_price") is None:
            return None

        # ---- fetch scan_result ------------------------------------------------
        scan_result = await self._db.pool.fetchrow(
            "SELECT id, score, confidence, signal_source "
            "FROM scan_results WHERE id = $1",
            trade["scan_result_id"],
        )
        if scan_result is None:
            logger.warning(
                "signal_performance: scan_result %s not found for trade %s",
                trade["scan_result_id"],
                trade.get("id"),
            )
            return None

        # ---- fetch regime at entry time ---------------------------------------
        opened_at = _parse_dt(trade["opened_at"])
        regime_row = await self._db.pool.fetchrow(
            "SELECT regime, "
            "CASE WHEN llm_confirmed THEN 0.9 ELSE 0.5 END AS regime_confidence "
            "FROM regime_snapshots "
            "WHERE symbol = $1 AND classified_at <= $2 "
            "ORDER BY classified_at DESC LIMIT 1",
            trade["symbol"],
            opened_at,
        )
        regime_at_entry = regime_row["regime"] if regime_row else None
        regime_confidence = float(regime_row["regime_confidence"]) if regime_row else None

        # ---- derived metrics -------------------------------------------------
        closed_at = _parse_dt(trade["closed_at"])
        hold_duration_minutes = _hold_minutes(opened_at, closed_at)

        entry = float(trade["entry_price"])
        exit_ = float(trade["exit_price"])
        if not entry:
            logger.warning("signal_performance: entry_price is 0 for trade %s", trade.get("id"))
            return None
        direction = (trade.get("signal_direction") or "buy").lower()

        if direction in ("sell", "short"):
            benchmark_bnh_pnl_pct = (entry - exit_) / entry * 100.0
        else:
            benchmark_bnh_pnl_pct = (exit_ - entry) / entry * 100.0

        tp_pct = float(trade.get("take_profit_pct") or 0)
        sl_pct = float(trade.get("stop_loss_pct") or 0)
        benchmark_random_expected_pnl = compute_random_expected_pnl(tp_pct, sl_pct)

        confidence_score = abs(scan_result["score"])
        is_win = (trade.get("net_pnl") or 0) > 0

        # ---- insert -----------------------------------------------------------
        row = {
            "trade_id": trade["id"],
            "account_id": trade["account_id"],
            "symbol": trade["symbol"],
            "direction": direction,
            "confidence_score": confidence_score,
            "confidence_tier": _score_to_tier(scan_result["score"]),
            "signal_source": scan_result.get("signal_source"),
            "regime_at_entry": regime_at_entry,
            "regime_confidence": regime_confidence,
            "entry_price": entry,
            "exit_price": exit_,
            "hold_duration_minutes": hold_duration_minutes,
            "realized_pnl_pct": float(trade.get("realized_pnl_pct") or 0),
            "net_pnl": float(trade.get("net_pnl") or 0),
            "fees": float(trade.get("fees") or 0),
            "close_reason": trade.get("close_reason"),
            "benchmark_bnh_pnl_pct": benchmark_bnh_pnl_pct,
            "benchmark_random_expected_pnl": benchmark_random_expected_pnl,
            "is_win": is_win,
            "opened_at": opened_at,
            "closed_at": closed_at,
        }

        await self._db.pool.execute(
            """
            INSERT INTO signal_performance (
                trade_id, account_id, symbol, direction,
                confidence_score, confidence_tier, signal_source,
                regime_at_entry, regime_confidence,
                entry_price, exit_price, hold_duration_minutes,
                realized_pnl_pct, net_pnl, fees, close_reason,
                benchmark_bnh_pnl_pct, benchmark_random_expected_pnl,
                is_win, opened_at, closed_at
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7,
                $8, $9,
                $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18,
                $19, $20, $21
            )
            ON CONFLICT (trade_id) DO NOTHING
            """,
            row["trade_id"],
            row["account_id"],
            row["symbol"],
            row["direction"],
            row["confidence_score"],
            row["confidence_tier"],
            row["signal_source"],
            row["regime_at_entry"],
            row["regime_confidence"],
            row["entry_price"],
            row["exit_price"],
            row["hold_duration_minutes"],
            row["realized_pnl_pct"],
            row["net_pnl"],
            row["fees"],
            row["close_reason"],
            row["benchmark_bnh_pnl_pct"],
            row["benchmark_random_expected_pnl"],
            row["is_win"],
            row["opened_at"],
            row["closed_at"],
        )

        # ---- optional decay hook ---------------------------------------------
        if self._decay is not None:
            try:
                await self._decay.check(row)
            except Exception:
                logger.exception(
                    "signal_performance: decay_detector.check raised for trade %s",
                    trade.get("id"),
                )

        return row


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime:
    """Coerce a datetime or ISO-8601 string to an aware ``datetime`` object.

    Args:
        value: A ``datetime`` instance or an ISO-8601 string.

    Returns:
        A UTC-aware ``datetime``.

    Raises:
        ValueError: If ``value`` cannot be parsed.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # ISO string
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _hold_minutes(opened_at: datetime, closed_at: datetime) -> float:
    """Compute trade hold duration in fractional minutes.

    Args:
        opened_at: Trade open timestamp (timezone-aware).
        closed_at: Trade close timestamp (timezone-aware).

    Returns:
        Duration in minutes as a float.  Returns 0.0 if ``closed_at`` is
        before ``opened_at``.
    """
    delta = closed_at - opened_at
    minutes = delta.total_seconds() / 60.0
    return max(0.0, minutes)
