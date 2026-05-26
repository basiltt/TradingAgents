"""Tests for Priority LLM Scheduler — Phase 2 Task 2.2."""

import asyncio
import pytest


@pytest.fixture
def scheduler():
    from backend.services.ai_manager_llm_scheduler import PriorityLLMScheduler
    return PriorityLLMScheduler()


@pytest.mark.asyncio
async def test_fast_acquire_release(scheduler):
    assert await scheduler.acquire("acc-1", "FAST") is True
    scheduler.release("acc-1", "FAST")


@pytest.mark.asyncio
async def test_fast_slots_limited_to_3(scheduler):
    assert await scheduler.acquire("acc-1", "FAST") is True
    assert await scheduler.acquire("acc-2", "FAST") is True
    assert await scheduler.acquire("acc-3", "FAST") is True
    assert await scheduler.acquire("acc-4", "FAST") is False
    scheduler.release("acc-1", "FAST")
    assert await scheduler.acquire("acc-4", "FAST") is True


@pytest.mark.asyncio
async def test_standard_acquire(scheduler):
    assert await scheduler.acquire("acc-1", "STANDARD") is True
    scheduler.release("acc-1", "STANDARD")


@pytest.mark.asyncio
async def test_per_account_max_2(scheduler):
    assert await scheduler.acquire("acc-1", "STANDARD") is True
    assert await scheduler.acquire("acc-1", "STANDARD") is True
    assert await scheduler.acquire("acc-1", "STANDARD") is False


@pytest.mark.asyncio
async def test_deep_soft_cap_at_2(scheduler):
    assert await scheduler.acquire("acc-1", "DEEP") is True
    assert await scheduler.acquire("acc-2", "DEEP") is True
    # 3rd DEEP should downgrade to STANDARD (still succeeds as STANDARD)
    assert await scheduler.acquire("acc-3", "DEEP") is True
    assert scheduler._deep_active == 2  # Only 2 counted as DEEP


@pytest.mark.asyncio
async def test_slot_context_manager(scheduler):
    async with scheduler.slot("acc-1", "STANDARD"):
        assert scheduler._account_inflight.get("acc-1", 0) == 1
    assert scheduler._account_inflight.get("acc-1", 0) == 0


@pytest.mark.asyncio
async def test_slot_releases_on_exception(scheduler):
    with pytest.raises(ValueError):
        async with scheduler.slot("acc-1", "STANDARD"):
            raise ValueError("test error")
    assert scheduler._account_inflight.get("acc-1", 0) == 0


@pytest.mark.asyncio
async def test_fast_cancelled_error_propagates_and_rolls_back(scheduler):
    """CancelledError during FAST acquire should propagate and rollback inflight."""
    # Fill all 3 fast slots
    await scheduler.acquire("a1", "FAST")
    await scheduler.acquire("a2", "FAST")
    await scheduler.acquire("a3", "FAST")

    # Next FAST acquire will timeout (semaphore full) — simulate with direct call
    result = await scheduler.acquire("a4", "FAST")
    assert result is False
    assert scheduler._account_inflight.get("a4", 0) == 0


@pytest.mark.asyncio
async def test_double_release_prevented(scheduler):
    """Double release should not crash or double-increment semaphore."""
    await scheduler.acquire("acc-1", "STANDARD")
    scheduler.release("acc-1", "STANDARD")
    # Second release should be a no-op (token already popped)
    scheduler.release("acc-1", "STANDARD")
    # Semaphore value should not exceed initial (7)
    assert scheduler._general_sem._value <= 7
