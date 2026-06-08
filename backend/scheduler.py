"""Lightweight async scheduler for periodic snapshot capture and cleanup."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


class SnapshotScheduler:
    def __init__(
        self,
        snapshot_fn: Optional[Callable[[], Coroutine[Any, Any, Any]]] = None,
        cleanup_fn: Optional[Callable[[], Coroutine[Any, Any, Any]]] = None,
        snapshot_interval: int = 300,
        cleanup_hour: int = 3,
        regime_fn: Any = None,
    ):
        self._snapshot_fn = snapshot_fn
        self._cleanup_fn = cleanup_fn
        self._snapshot_interval = snapshot_interval
        self._cleanup_hour = cleanup_hour
        self._regime_fn = regime_fn
        self._snapshot_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._regime_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._snapshot_fn is not None:
            self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        if self._cleanup_fn is not None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        if self._regime_fn is not None:
            self._regime_task = asyncio.create_task(self._regime_loop())
        logger.info("SnapshotScheduler started (interval=%ds)", self._snapshot_interval)

    async def shutdown(self) -> None:
        self._running = False
        for task in (self._snapshot_task, self._cleanup_task, self._regime_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("SnapshotScheduler stopped")

    async def _snapshot_loop(self) -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                if self._snapshot_fn is not None:
                    await self._snapshot_fn()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduled snapshot failed")
            try:
                await asyncio.sleep(self._snapshot_interval)
            except asyncio.CancelledError:
                break

    async def _cleanup_loop(self) -> None:
        import datetime
        while self._running:
            now = datetime.datetime.now(datetime.timezone.utc)
            target = now.replace(hour=self._cleanup_hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            wait_seconds = min((target - now).total_seconds(), 25 * 3600)
            try:
                await asyncio.sleep(wait_seconds)
                if self._cleanup_fn is not None:
                    await self._cleanup_fn()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduled cleanup failed")

    async def _regime_loop(self) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                await self._regime_fn()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduled regime classification failed")
            try:
                await asyncio.sleep(900)
            except asyncio.CancelledError:
                break
