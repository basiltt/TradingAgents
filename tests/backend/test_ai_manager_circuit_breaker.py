"""Tests for AI Manager Circuit Breaker — Phase 2 Task 2.6."""

import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def breaker():
    from backend.services.ai_manager_circuit_breaker import AIManagerCircuitBreaker
    return AIManagerCircuitBreaker(threshold=3, cooldown_s=3600, repo=None)


@pytest.mark.asyncio
async def test_not_tripped_initially(breaker):
    assert breaker.is_tripped("acc-1") is False


@pytest.mark.asyncio
async def test_loss_counting_only_close_actions(breaker):
    await breaker.record_outcome("acc-1", -100, "ADJUST_TP")
    assert breaker.is_tripped("acc-1") is False
    assert breaker._counts.get("acc-1", 0) == 0


@pytest.mark.asyncio
async def test_trips_after_threshold_losses(breaker):
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -30, "FULL_CLOSE")
    assert breaker.is_tripped("acc-1") is False
    await breaker.record_outcome("acc-1", -20, "PARTIAL_CLOSE")
    assert breaker.is_tripped("acc-1") is True


@pytest.mark.asyncio
async def test_profit_resets_count(breaker):
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", 10, "FULL_CLOSE")
    assert breaker._counts["acc-1"] == 0
    assert breaker.is_tripped("acc-1") is False


@pytest.mark.asyncio
async def test_profit_during_half_open_resets(breaker):
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    assert breaker.is_tripped("acc-1") is True
    # Simulate half-open action with profit
    await breaker.record_outcome("acc-1", 10, "FULL_CLOSE")
    assert breaker.is_tripped("acc-1") is False


@pytest.mark.asyncio
async def test_loss_while_open_does_not_reset_tripped_at(breaker):
    """Additional losses while already OPEN should not reset tripped_at."""
    import time
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    assert breaker.is_tripped("acc-1") is True
    original_tripped_at = breaker._tripped_at["acc-1"]

    # Additional loss while already open
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    assert breaker._counts["acc-1"] == 4
    assert breaker._tripped_at["acc-1"] == original_tripped_at


@pytest.mark.asyncio
async def test_restart_cooldown(breaker):
    """restart_cooldown resets the tripped_at timer."""
    import time
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    await breaker.record_outcome("acc-1", -50, "FULL_CLOSE")
    original = breaker._tripped_at["acc-1"]
    breaker.restart_cooldown("acc-1")
    assert breaker._tripped_at["acc-1"] >= original
    assert breaker.is_tripped("acc-1") is True


@pytest.mark.asyncio
async def test_rehydration(breaker):
    await breaker.load_from_db("acc-1", count=3, active=True)
    assert breaker.is_tripped("acc-1") is True
    assert breaker._counts["acc-1"] == 3
