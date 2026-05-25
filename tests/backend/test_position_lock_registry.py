"""Tests for Position Lock Registry — Phase 2 Task 2.1."""

import asyncio
import pytest
import time


@pytest.fixture
def registry():
    from backend.services.position_lock_registry import PositionLockRegistry
    return PositionLockRegistry()


@pytest.mark.asyncio
async def test_acquire_and_release(registry):
    assert await registry.acquire("acc-1", "BTCUSDT") is True
    registry.release("acc-1", "BTCUSDT")


@pytest.mark.asyncio
async def test_acquire_timeout(registry):
    await registry.acquire("acc-1", "BTCUSDT")
    result = await registry.acquire("acc-1", "BTCUSDT", timeout=0.1)
    assert result is False
    registry.release("acc-1", "BTCUSDT")


@pytest.mark.asyncio
async def test_concurrent_acquire_one_wins(registry):
    results = []

    async def try_acquire(name):
        got = await registry.acquire("acc-1", "ETHUSDT", timeout=0.2)
        results.append((name, got))
        if got:
            await asyncio.sleep(0.3)
            registry.release("acc-1", "ETHUSDT")

    await asyncio.gather(try_acquire("A"), try_acquire("B"))
    wins = [r for r in results if r[1] is True]
    losses = [r for r in results if r[1] is False]
    assert len(wins) == 1
    assert len(losses) == 1


@pytest.mark.asyncio
async def test_cleanup_account(registry):
    await registry.acquire("acc-1", "BTCUSDT")
    registry.release("acc-1", "BTCUSDT")
    await registry.acquire("acc-1", "ETHUSDT")
    registry.release("acc-1", "ETHUSDT")

    await registry.cleanup_account("acc-1")
    assert ("acc-1", "BTCUSDT") not in registry._locks
    assert ("acc-1", "ETHUSDT") not in registry._locks


@pytest.mark.asyncio
async def test_cleanup_skips_held_locks(registry):
    await registry.acquire("acc-1", "BTCUSDT")
    await registry.cleanup_account("acc-1")
    # Held lock should NOT be removed
    assert ("acc-1", "BTCUSDT") in registry._locks
    registry.release("acc-1", "BTCUSDT")


@pytest.mark.asyncio
async def test_evict_stale(registry):
    await registry.acquire("acc-1", "BTCUSDT")
    registry.release("acc-1", "BTCUSDT")
    # Hack last_used to simulate staleness
    registry._last_used[("acc-1", "BTCUSDT")] = time.monotonic() - 400

    await registry.evict_stale(max_idle_s=300.0)
    assert ("acc-1", "BTCUSDT") not in registry._locks


@pytest.mark.asyncio
async def test_evict_stale_skips_held(registry):
    await registry.acquire("acc-1", "BTCUSDT")
    registry._last_used[("acc-1", "BTCUSDT")] = time.monotonic() - 400

    await registry.evict_stale(max_idle_s=300.0)
    # Held lock should NOT be evicted
    assert ("acc-1", "BTCUSDT") in registry._locks
    registry.release("acc-1", "BTCUSDT")
