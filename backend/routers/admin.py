"""Admin router — operator controls for feature kill switches (API §K, FR-007).

`POST /admin/kill-switch {feature_name, enabled}` upserts a row in
`feature_kill_switches`. The spec's `enabled` is the operator-facing sense; the
table stores `killed` (the inverse), and the scan-time reader fails closed. A
master `__all__` feature name disables every regime feature at once.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import KillSwitchRequest
from backend.services import kill_switch as _ks

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

# Feature keys the kill switch understands (master + per-feature). Rejecting unknown
# names stops a typo from silently creating a no-op row that looks like protection.
_VALID_FEATURES = {"__all__", "f1", "f2", "f2_long"}


def _get_db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, detail="Database not available")
    return db


@router.get("/admin/kill-switch")
async def get_kill_switches(request: Request):
    """Return the current feature kill-switch map ({feature_name: killed})."""
    db = _get_db(request)
    kill = await _ks.read_kill_switches(db)
    return {"kill_switches": kill}


@router.post("/admin/kill-switch")
async def set_kill_switch(request: Request, body: KillSwitchRequest):
    """Upsert a feature kill switch. ``enabled=false`` kills the feature.

    Audit-logged with the operator identity (``updated_by``). Returns the resulting
    state so the caller can confirm the flip took.
    """
    if body.feature_name not in _VALID_FEATURES:
        raise HTTPException(
            422,
            detail=f"Unknown feature_name '{body.feature_name}'. Valid: {sorted(_VALID_FEATURES)}",
        )
    db = _get_db(request)
    killed = not body.enabled  # operator 'enabled' == not killed
    ok = await _ks.set_kill_switch(db, body.feature_name, killed, updated_by=body.updated_by or "admin")
    if not ok:
        raise HTTPException(500, detail="Failed to persist kill switch")
    logger.warning(
        "feature_kill_switch_flipped",
        extra={"feature": body.feature_name, "enabled": body.enabled, "by": body.updated_by or "admin"},
    )
    return {"feature_name": body.feature_name, "enabled": body.enabled, "killed": killed}
