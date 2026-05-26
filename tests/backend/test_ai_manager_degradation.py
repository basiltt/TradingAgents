"""Tests for Degradation Tier Manager — Phase 2 Task 2.8."""

import pytest
import time
from unittest.mock import AsyncMock, patch


@pytest.fixture
def manager():
    from backend.services.ai_manager_degradation import DegradationTierManager
    return DegradationTierManager(repo=None)


@pytest.mark.asyncio
async def test_initial_tier_is_zero(manager):
    assert manager.get_tier() == 0


@pytest.mark.asyncio
async def test_timeout_escalates_to_tier_1(manager):
    await manager.check_health("timeout")
    assert manager.get_tier() == 1


@pytest.mark.asyncio
async def test_unavailable_escalates_to_tier_2(manager):
    await manager.check_health("unavailable")
    assert manager.get_tier() == 2


@pytest.mark.asyncio
async def test_exchange_down_escalates_to_tier_3(manager):
    await manager.check_health("exchange_down")
    assert manager.get_tier() == 3


@pytest.mark.asyncio
async def test_success_does_nothing_at_tier_0(manager):
    await manager.check_health("success")
    assert manager.get_tier() == 0


@pytest.mark.asyncio
async def test_recovery_requires_hysteresis(manager):
    await manager.check_health("timeout")
    assert manager.get_tier() == 1
    # Single success doesn't recover
    await manager.check_health("success")
    assert manager.get_tier() == 1


@pytest.mark.asyncio
async def test_recovery_with_elapsed_hysteresis(manager):
    await manager.check_health("timeout")
    assert manager.get_tier() == 1
    # Start health streak
    await manager.check_health("success")
    # Hack the streak start to simulate 5 min elapsed
    manager._health_streak_start = time.monotonic() - 301
    await manager.check_health("success")
    assert manager.get_tier() == 0


@pytest.mark.asyncio
async def test_failure_resets_health_streak(manager):
    await manager.check_health("timeout")
    await manager.check_health("success")
    start = manager._health_streak_start
    assert start > 0
    await manager.check_health("timeout")
    assert manager._health_streak_start == 0.0


@pytest.mark.asyncio
async def test_should_use_llm(manager):
    assert manager.should_use_llm() is True
    await manager.check_health("timeout")
    assert manager.should_use_llm() is True  # tier 1 still uses LLM (skip DEEP only)
    await manager.check_health("unavailable")
    assert manager.should_use_llm() is False  # tier 2 = rule-based only


@pytest.mark.asyncio
async def test_rehydration_from_db():
    from backend.services.ai_manager_degradation import DegradationTierManager

    mock_repo = AsyncMock()
    mock_repo.get_degradation_tier = AsyncMock(return_value=2)
    mgr = DegradationTierManager(repo=mock_repo)
    await mgr.load_from_db()
    assert mgr.get_tier() == 2
