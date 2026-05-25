"""Tests for AI Manager Memory — Phase 3 Task 3.3."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_recent_decisions = AsyncMock(return_value=[
        {"action_taken": {"action": "FULL_CLOSE", "symbol": "BTCUSDT"}, "confidence": 0.85, "outcome_label": "profitable"},
        {"action_taken": {"action": "HOLD", "symbol": ""}, "confidence": 0.5, "outcome_label": None},
    ])
    repo.get_patterns = AsyncMock(return_value=[
        {"pattern_type": "reversal", "symbol": "BTCUSDT", "description": "RSI divergence pattern", "confidence": 0.8},
    ])
    repo.count_decisions = AsyncMock(return_value=2)
    return repo


@pytest.fixture
def memory(mock_repo):
    from backend.services.ai_manager_memory import AIManagerMemory
    return AIManagerMemory(repo=mock_repo)


@pytest.mark.asyncio
async def test_episodic_context_summarizes(memory):
    result = await memory.get_episodic_context("acc-1")
    assert len(result) == 2
    assert result[0]["action"] == "FULL_CLOSE"
    assert result[0]["symbol"] == "BTCUSDT"
    assert result[0]["outcome_label"] == "profitable"


@pytest.mark.asyncio
async def test_episodic_context_handles_none_action(memory, mock_repo):
    mock_repo.get_recent_decisions.return_value = [{"action_taken": None, "confidence": 0.5, "outcome_label": None}]
    result = await memory.get_episodic_context("acc-1")
    assert result[0]["action"] == "HOLD"


@pytest.mark.asyncio
async def test_semantic_patterns(memory):
    result = await memory.get_semantic_patterns("acc-1")
    assert len(result) == 1
    assert result[0]["type"] == "reversal"
    assert len(result[0]["description"]) <= 200


@pytest.mark.asyncio
async def test_decision_count(memory, mock_repo):
    count = await memory.get_decision_count("acc-1")
    assert count == 2


# === generate_patterns tests ===


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"cnt": 10})
    conn.fetch = AsyncMock(return_value=[
        {"id": i, "account_id": "acc-1", "timestamp": None,
         "action_taken": {"action": "HOLD", "symbol": "BTCUSDT"},
         "confidence": 0.7, "outcome_label": "profitable"}
        for i in range(10)
    ])
    conn.execute = AsyncMock()
    return conn


@pytest.fixture
def mock_repo_with_lock(mock_repo, mock_conn):
    async def _locked(account_id, callback):
        return await callback(account_id, mock_conn)
    mock_repo.generate_patterns_locked = _locked
    return mock_repo


@pytest.fixture
def memory_with_lock(mock_repo_with_lock):
    from backend.services.ai_manager_memory import AIManagerMemory
    return AIManagerMemory(repo=mock_repo_with_lock)


@pytest.mark.asyncio
async def test_generate_patterns_no_callable(memory):
    result = await memory.generate_patterns("acc-1", llm_callable=None)
    assert result == 0


@pytest.mark.asyncio
async def test_generate_patterns_fewer_than_5_decisions(memory_with_lock, mock_conn):
    mock_conn.fetch = AsyncMock(return_value=[{"id": 1}] * 3)
    llm = AsyncMock()
    result = await memory_with_lock.generate_patterns("acc-1", llm_callable=llm)
    assert result == 0
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_generate_patterns_happy_path(memory_with_lock, mock_conn):
    llm = AsyncMock(return_value=[
        {"type": "reversal", "symbol": "BTCUSDT", "description": "RSI divergence", "confidence": 0.8},
        {"type": "momentum", "symbol": "ETHUSDT", "description": "Strong trend", "confidence": 0.6},
    ])
    result = await memory_with_lock.generate_patterns("acc-1", llm_callable=llm)
    assert result == 2
    assert mock_conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_generate_patterns_50_cap_deactivates(memory_with_lock, mock_conn):
    mock_conn.fetchrow = AsyncMock(return_value={"cnt": 50})
    llm = AsyncMock(return_value=[
        {"type": "t", "symbol": "S", "description": "d", "confidence": 0.5},
    ])
    await memory_with_lock.generate_patterns("acc-1", llm_callable=llm)
    # First execute call should be the deactivation UPDATE
    first_call = mock_conn.execute.call_args_list[0]
    assert "UPDATE" in first_call[0][0]


@pytest.mark.asyncio
async def test_generate_patterns_empty_description_skipped(memory_with_lock, mock_conn):
    llm = AsyncMock(return_value=[
        {"type": "t", "symbol": "S", "description": "", "confidence": 0.5},
        {"type": "t2", "symbol": "S2", "description": "valid", "confidence": 0.7},
    ])
    result = await memory_with_lock.generate_patterns("acc-1", llm_callable=llm)
    assert result == 1


@pytest.mark.asyncio
async def test_generate_patterns_llm_timeout(memory_with_lock, mock_conn):
    async def slow_llm(prompt):
        await asyncio.sleep(100)
        return []

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            memory_with_lock.generate_patterns("acc-1", llm_callable=slow_llm),
            timeout=1.0,
        )
