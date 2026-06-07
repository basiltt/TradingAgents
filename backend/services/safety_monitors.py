"""FR-065 safety monitors: F2-long drawdown breaker + F1 suppression-rate alert.

Two server-side guards with thresholds pinned as CONSTANTS (SD22 — NOT part of the
AutoTradeConfig table, so they cannot be tuned into uselessness per-account):

  * F2-long circuit breaker: auto-disable the live-long side when the rolling
    drawdown over the last ``F2_LONG_BREAKER_TRADES`` (20) closed MR-long trades is
    worse than ``F2_LONG_BREAKER_DRAWDOWN_PCT`` (-15%). Tripping sets the ``f2_long``
    kill switch (fail-closed read already enforced elsewhere).
  * F1 suppression alert: warn when the session/vol filter suppressed > 95% of
    candidate entries over the last ``F1_ALERT_SCANS`` (8) scans — a sign F1 is
    silently strangling the book rather than shaping it.

Pure decision helpers (``breaker_should_trip``, ``suppression_should_alert``) are
split from the DB-backed driver so the trip points are unit-testable without a
database (T-18 asserts exact boundaries).
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from backend.services import kill_switch

logger = logging.getLogger(__name__)

# --- pinned server-side constants (SD22) -----------------------------------------
F2_LONG_BREAKER_TRADES = 20
F2_LONG_BREAKER_DRAWDOWN_PCT = -15.0
F1_ALERT_SCANS = 8
F1_SUPPRESSION_ALERT_RATE = 0.95


def breaker_should_trip(
    pnl_pcts: Sequence[float],
    *,
    window: int = F2_LONG_BREAKER_TRADES,
    threshold_pct: float = F2_LONG_BREAKER_DRAWDOWN_PCT,
) -> bool:
    """True when the summed PnL% over the last ``window`` MR-long trades <= threshold.

    Requires a full window — fewer than ``window`` trades never trips (not enough
    evidence). ``pnl_pcts`` is newest-first or oldest-first agnostic because we sum
    the last ``window`` by position; the caller passes a recent slice.
    """
    if len(pnl_pcts) < window:
        return False
    recent = list(pnl_pcts)[-window:]
    return sum(recent) <= threshold_pct


def suppression_should_alert(
    suppressed: int,
    total: int,
    *,
    rate: float = F1_SUPPRESSION_ALERT_RATE,
) -> bool:
    """True when suppressed/total strictly exceeds ``rate``. Empty candidate set never alerts."""
    if total <= 0:
        return False
    return (suppressed / total) > rate


async def check_f2_long_breaker(db: Any, account_id: str, *, updated_by: str = "fr065_breaker") -> bool:
    """Evaluate the breaker for one account; trip the ``f2_long`` kill on breach.

    Returns True if the breaker tripped (and the kill write was attempted). Fail-open:
    a query error logs and returns False so a transient DB blip never auto-disables a
    strategy on bad data.
    """
    try:
        rows = await db.pool.fetch(
            "SELECT realized_pnl_pct FROM trades "
            "WHERE account_id = $1 AND strategy_kind = 'mean_reversion' AND side = 'Buy' "
            "AND status = 'closed' AND realized_pnl_pct IS NOT NULL "
            "AND parent_trade_id IS NULL "
            "ORDER BY closed_at DESC LIMIT $2",
            account_id, F2_LONG_BREAKER_TRADES,
        )
    except Exception:
        logger.warning("f2_long_breaker_query_failed", exc_info=True)
        return False
    pnl_pcts = [float(r["realized_pnl_pct"]) for r in rows]
    if not breaker_should_trip(pnl_pcts):
        return False
    logger.error(
        "f2_long_breaker_tripped",
        extra={"account_id": account_id, "rolling_drawdown_pct": sum(pnl_pcts), "trades": len(pnl_pcts)},
    )
    persisted = await kill_switch.set_kill_switch(db, "f2_long", True, updated_by=updated_by)
    if not persisted:
        # The in-scan kill still applies (caller flips the local kill dict), but the
        # next scan's reader won't see it. Surface loudly so the gap is visible.
        logger.error("f2_long_breaker_kill_write_failed", extra={"account_id": account_id})
    return True


def f1_suppression_alert(scan_suppressions: Sequence[tuple[int, int]]) -> Optional[float]:
    """Aggregate (suppressed, total) over recent scans; return the rate if it alerts, else None.

    ``scan_suppressions`` is the last ``F1_ALERT_SCANS`` scans' (suppressed, candidate)
    counts. Returns the aggregate suppression rate when it breaches the alert threshold
    (so the caller can log/notify with the number), else None.
    """
    window = list(scan_suppressions)[-F1_ALERT_SCANS:]
    suppressed = sum(s for s, _ in window)
    total = sum(t for _, t in window)
    if suppression_should_alert(suppressed, total):
        logger.warning("f1_suppression_alert", extra={"rate": suppressed / total, "scans": len(window)})
        return suppressed / total
    return None
