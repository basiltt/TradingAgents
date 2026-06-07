"""Feature kill-switch reader (Phase 1 TASK-1.6).

Read UNCONDITIONALLY in start_scan (NOT inside the precompute predicate, R3-F1) so
master/per-feature kills are enforced even for fleets that never trigger precompute.
Semantics (R2-F2): the `kill` dict value IS the feature_kill_switches.killed column
verbatim. No row = not killed. A read FAILURE => fail-closed ({"__all__": True}).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def read_kill_switches(db: Any) -> dict[str, bool]:
    """Return {feature_name: killed}. Fail-closed (assume all killed) on any error."""
    try:
        rows = await db.pool.fetch("SELECT feature_name, killed FROM feature_kill_switches")
        return {row["feature_name"]: bool(row["killed"]) for row in rows}
    except Exception:
        logger.warning("kill_switch_read_failed_failing_closed", exc_info=True)
        return {"__all__": True}


def is_killed(kill: dict[str, bool], feature: str) -> bool:
    """True if the master __all__ kill is set OR this feature is individually killed."""
    return bool(kill.get("__all__") or kill.get(feature, False))


async def set_kill_switch(db: Any, feature: str, killed: bool, *, updated_by: str = "system") -> bool:
    """Upsert a feature kill flag. Returns True on success, False on failure (never raises).

    Used by the FR-065 safety auto-disable to trip ``f2_long`` when the rolling-drawdown
    breaker fires. Writing failures must not abort the scan, so the caller treats False
    as "could not persist" and logs — the next scan's reader still fails closed on a
    broken table.
    """
    from datetime import datetime, timezone
    try:
        await db.pool.execute(
            "INSERT INTO feature_kill_switches (feature_name, killed, updated_by, updated_at) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (feature_name) DO UPDATE SET "
            "killed = EXCLUDED.killed, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at",
            feature, killed, updated_by, datetime.now(timezone.utc),
        )
        return True
    except Exception:
        logger.warning("kill_switch_write_failed", exc_info=True)
        return False
