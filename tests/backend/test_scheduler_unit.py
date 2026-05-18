"""Unit tests for SnapshotScheduler — covers start, shutdown, loop cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.scheduler import SnapshotScheduler


@pytest.fixture
def snapshot_fn():
    return AsyncMock()


@pytest.fixture
def cleanup_fn():
    return AsyncMock()


class TestSnapshotScheduler:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_creates_tasks(self, snapshot_fn, cleanup_fn):
        sched = SnapshotScheduler(snapshot_fn, cleanup_fn, snapshot_interval=60)
        await sched.start()
        assert sched._running is True
        assert sched._snapshot_task is not None
        assert sched._cleanup_task is not None
        await sched.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_idempotent(self, snapshot_fn, cleanup_fn):
        sched = SnapshotScheduler(snapshot_fn, cleanup_fn)
        await sched.start()
        task1 = sched._snapshot_task
        await sched.start()
        assert sched._snapshot_task is task1
        await sched.shutdown()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_cancels_tasks(self, snapshot_fn, cleanup_fn):
        sched = SnapshotScheduler(snapshot_fn, cleanup_fn, snapshot_interval=60)
        await sched.start()
        await sched.shutdown()
        assert sched._running is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_without_start(self, snapshot_fn, cleanup_fn):
        sched = SnapshotScheduler(snapshot_fn, cleanup_fn)
        await sched.shutdown()
        assert sched._running is False
