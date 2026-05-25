"""Tests for AI Manager Repository — Phase 1 Task 1.3."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from contextlib import asynccontextmanager


class MockPool:
    def __init__(self):
        self.conn = AsyncMock()

    def acquire(self):
        conn = self.conn
        class CM:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *args):
                pass
        return CM()


@pytest.fixture
def mock_pool():
    return MockPool()


@pytest.fixture
def repo(mock_pool):
    from backend.services.ai_manager_repository import AIManagerRepository
    return AIManagerRepository(mock_pool)


@pytest.mark.asyncio
async def test_get_state_returns_none_when_not_found(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value=None)
    result = await repo.get_state("acc-123")
    assert result is None


@pytest.mark.asyncio
async def test_get_state_returns_dict_when_found(repo, mock_pool):
    row = {"account_id": "acc-123", "enabled": True, "fsm_state": "sleeping"}
    mock_pool.conn.fetchrow = AsyncMock(return_value=row)
    result = await repo.get_state("acc-123")
    assert result == row


@pytest.mark.asyncio
async def test_upsert_state_calls_execute(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value={"account_id": "acc-123"})
    result = await repo.upsert_state("acc-123", enabled=True, fsm_state="monitoring")
    assert result is not None


@pytest.mark.asyncio
async def test_increment_actions_atomic_within_budget(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value={"account_id": "acc-123"})
    result = await repo.increment_actions_atomic("acc-123")
    assert result is True


@pytest.mark.asyncio
async def test_increment_actions_atomic_exceeds_budget(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value=None)
    result = await repo.increment_actions_atomic("acc-123")
    assert result is False


@pytest.mark.asyncio
async def test_increment_token_budget_within_limit(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value={"account_id": "acc-123"})
    result = await repo.increment_token_budget_atomic("acc-123", 500, 100000)
    assert result is True


@pytest.mark.asyncio
async def test_increment_token_budget_exceeds_limit(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value=None)
    result = await repo.increment_token_budget_atomic("acc-123", 500, 100000)
    assert result is False


@pytest.mark.asyncio
async def test_record_realized_loss_atomic(repo, mock_pool):
    mock_pool.conn.fetchrow = AsyncMock(return_value={"realized_loss_today": 150.5, "equity_at_day_start": 10000.0})
    result = await repo.record_realized_loss("acc-123", 50.25)
    assert result["realized_loss_today"] == 150.5


@pytest.mark.asyncio
async def test_set_kill_switch(repo, mock_pool):
    mock_pool.conn.execute = AsyncMock()
    await repo.set_kill_switch("acc-123", True)
    mock_pool.conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_recent_decisions(repo, mock_pool):
    rows = [
        {"id": 1, "account_id": "acc-123", "timestamp": datetime.now(timezone.utc),
         "action_taken": "{}", "confidence": 0.8, "outcome_label": "profitable"}
    ]
    mock_pool.conn.fetch = AsyncMock(return_value=rows)
    result = await repo.get_recent_decisions("acc-123", limit=15)
    assert len(result) == 1
    assert result[0]["confidence"] == 0.8


@pytest.mark.asyncio
async def test_upsert_state_rejects_invalid_columns(repo):
    """Invalid column names should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid columns"):
        await repo.upsert_state("acc-123", bogus_column="bad")


@pytest.mark.asyncio
async def test_update_decision_outcome_pnl_boundary(repo, mock_pool):
    """PnL at exactly 0.5 should be 'neutral', at 0.51 should be 'profitable'."""
    mock_pool.conn.execute = AsyncMock()

    # 0.5 → neutral (not > 0.5)
    await repo.update_decision_outcome(1, datetime.now(timezone.utc), {"realized_pnl": 0.5})
    call_args = mock_pool.conn.execute.call_args[0]
    assert call_args[1] is not None  # outcome json
    assert call_args[2] == "neutral"

    mock_pool.conn.execute.reset_mock()

    # 0.51 → profitable
    await repo.update_decision_outcome(2, datetime.now(timezone.utc), {"realized_pnl": 0.51})
    call_args = mock_pool.conn.execute.call_args[0]
    assert call_args[2] == "profitable"

    mock_pool.conn.execute.reset_mock()

    # -0.5 → neutral (not < -0.5)
    await repo.update_decision_outcome(3, datetime.now(timezone.utc), {"realized_pnl": -0.5})
    call_args = mock_pool.conn.execute.call_args[0]
    assert call_args[2] == "neutral"

    mock_pool.conn.execute.reset_mock()

    # -0.51 → loss
    await repo.update_decision_outcome(4, datetime.now(timezone.utc), {"realized_pnl": -0.51})
    call_args = mock_pool.conn.execute.call_args[0]
    assert call_args[2] == "loss"


@pytest.mark.asyncio
async def test_update_decision_outcome_none_pnl_fields(repo, mock_pool):
    """When all PnL fields are None, outcome_label should be 'neutral'."""
    mock_pool.conn.execute = AsyncMock()
    await repo.update_decision_outcome(5, datetime.now(timezone.utc), {"some_field": "x"})
    call_args = mock_pool.conn.execute.call_args[0]
    assert call_args[2] == "neutral"


@pytest.mark.asyncio
async def test_update_decision_outcome_empty_outcome(repo, mock_pool):
    """Empty dict outcome is falsy — outcome_label should be None."""
    mock_pool.conn.execute = AsyncMock()
    await repo.update_decision_outcome(6, datetime.now(timezone.utc), {})
    call_args = mock_pool.conn.execute.call_args[0]
    assert call_args[2] is None
