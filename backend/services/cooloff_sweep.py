"""CooloffSweep — periodic per-account cool-off classification (authoritative net).

Models PositionReconciler: a background asyncio loop that, every COOLOFF_SWEEP_INTERVAL_S
(default 60s), calls CooloffClassifier.maybe_classify for every active account. This is the
authoritative driver — the post-commit trigger in trade_service is only a latency optimization
and the gate-time call only closes the resume window; the sweep guarantees eventual
classification even if both are dropped. maybe_classify is fully fail-open, so one account's
error never stops the loop.

Spec: FR-008(b), arch §3(b)/§11.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_INITIAL_DELAY_S = 30
_DEFAULT_INTERVAL_S = 60


def _parse_interval(raw: str | None) -> int:
    """Parse COOLOFF_SWEEP_INTERVAL_S → a positive int, else the default.

    A malformed env value (e.g. "60s", "", "abc") must NEVER crash startup — this
    constructor runs at app boot outside any try/except. Falls back to the default for
    None / non-numeric / <1 values (a 0 or negative would otherwise busy-loop).
    """
    if raw is None:
        return _DEFAULT_INTERVAL_S
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_INTERVAL_S
    return val if val >= 1 else _DEFAULT_INTERVAL_S


class CooloffSweep:
    def __init__(self, db: Any, classifier: Any, accounts_service: Any):
        self._db = db
        self._classifier = classifier
        self._accounts_service = accounts_service
        self._task: asyncio.Task | None = None
        self._interval = _parse_interval(os.environ.get("COOLOFF_SWEEP_INTERVAL_S"))
        self._enabled = os.environ.get("COOLOFF_SWEEP_ENABLED", "true").lower() != "false"

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Cooloff sweep disabled via COOLOFF_SWEEP_ENABLED=false")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Cooloff sweep started (interval=%ds)", self._interval)

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cooloff sweep stopped")

    async def _loop(self) -> None:
        try:
            await asyncio.sleep(_INITIAL_DELAY_S)
        except asyncio.CancelledError:
            return
        while True:
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 — never let the loop die
                logger.exception("cooloff_sweep_loop_error")
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _sweep_once(self) -> None:
        accounts = await self._db.list_accounts()
        for account in accounts:
            if not account.get("is_active"):
                continue
            account_id = str(account["id"])
            # maybe_classify is fully fail-open, but guard the loop anyway.
            try:
                await self._classifier.maybe_classify(account_id)
            except Exception:  # noqa: BLE001
                logger.warning("cooloff_sweep_account_error", extra={"account_id": account_id})
