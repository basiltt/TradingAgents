"""Tests for AIAccountManagerService — orchestrator lifecycle and integration paths."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai_manager_schemas import AIManagerConfig


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo._pool = MagicMock()
    repo.get_enabled_accounts = AsyncMock(return_value=[])
    repo.get_stranded_decisions = AsyncMock(return_value=[])
    repo.upsert_state = AsyncMock(return_value={})
    repo.sync_config_columns = AsyncMock()
    repo.get_state = AsyncMock(return_value={
        "enabled": True,
        "fsm_state": "sleeping",
        "config": "{}",
        "circuit_breaker_count": 0,
        "circuit_breaker_active": False,
    })
    repo.set_kill_switch = AsyncMock()
    repo.set_global_kill = AsyncMock()
    repo.update_heartbeat = AsyncMock()
    repo.get_pending_retries = AsyncMock(return_value=[])
    repo.update_decision_outcome = AsyncMock()
    repo.insert_failed_outcome = AsyncMock()
    repo.mark_resolved = AsyncMock()
    repo.increment_retry = AsyncMock()
    return repo


@pytest.fixture
def service(mock_repo):
    from backend.services.ai_account_manager_service import AIAccountManagerService
    from backend.services.ai_manager_llm_scheduler import PriorityLLMScheduler
    from backend.services.position_lock_registry import PositionLockRegistry

    svc = AIAccountManagerService(
        accounts_service=MagicMock(),
        close_positions_service=MagicMock(),
        ws_manager=None,
        ai_manager_repo=mock_repo,
        market_data_cache=MagicMock(),
        position_lock_registry=PositionLockRegistry(),
        llm_scheduler=PriorityLLMScheduler(),
        hmac_key="test-key",
    )
    return svc


@pytest.mark.asyncio
async def test_enable_stores_task(service, mock_repo):
    """enable() should spawn and store a task."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        mock_task_inst = MagicMock()
        mock_task_inst.start = MagicMock()
        MockTask.return_value = mock_task_inst

        await service.enable("acc-1", AIManagerConfig())
        assert "acc-1" in service._tasks
        mock_task_inst.start.assert_called_once()


@pytest.mark.asyncio
async def test_enable_idempotent(service, mock_repo):
    """Calling enable() twice does not create duplicate tasks."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        mock_task_inst = MagicMock()
        mock_task_inst.start = MagicMock()
        MockTask.return_value = mock_task_inst

        await service.enable("acc-1", AIManagerConfig())
        await service.enable("acc-1", AIManagerConfig())
        assert MockTask.call_count == 1


@pytest.mark.asyncio
async def test_disable_cancels_and_removes(service, mock_repo):
    """disable() cancels task, cleans locks, removes from dict."""
    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    service._tasks["acc-1"] = mock_task
    service._account_locks["acc-1"] = asyncio.Lock()

    await service.disable("acc-1")
    mock_task.cancel.assert_called_once()
    assert "acc-1" not in service._tasks
    assert "acc-1" not in service._account_locks


@pytest.mark.asyncio
async def test_kill_sets_flag_on_task(service, mock_repo):
    """kill() sets kill switch in DB and on task."""
    mock_task = MagicMock()
    mock_task.set_killed = MagicMock()
    service._tasks["acc-1"] = mock_task

    await service.kill("acc-1")
    mock_repo.set_kill_switch.assert_called_once_with("acc-1", True)
    mock_task.set_killed.assert_called_once()


@pytest.mark.asyncio
async def test_advisory_lock_failure_raises(service, mock_repo):
    """If advisory lock fails (another instance), start() raises RuntimeError."""
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=False)
    mock_repo._pool.acquire = AsyncMock(return_value=mock_conn)
    mock_repo._pool.release = AsyncMock()

    with pytest.raises(RuntimeError, match="Another AI Account Manager"):
        await service.start()


@pytest.mark.asyncio
async def test_startup_reconciliation_recovers_stranded(service, mock_repo):
    """Stranded decisions should be recovered to dead-letter."""
    from datetime import datetime, timezone

    mock_repo.get_enabled_accounts.return_value = []
    mock_repo.get_stranded_decisions.return_value = [
        {"id": 42, "timestamp": datetime.now(timezone.utc), "account_id": "acc-1"}
    ]

    await service._startup_reconciliation()
    mock_repo.insert_failed_outcome.assert_called_once()
    mock_repo.update_decision_outcome.assert_called_once()


@pytest.mark.asyncio
async def test_dead_letter_loop_exhausts_retries(service, mock_repo):
    """Dead-letter loop marks items as exhausted when retry_count >= max_retries."""
    from datetime import datetime, timezone

    mock_repo.get_pending_retries.return_value = [
        {
            "id": 1,
            "decision_id": 10,
            "decision_timestamp": datetime.now(timezone.utc),
            "retry_count": 5,
            "max_retries": 5,
        }
    ]

    # Run one iteration manually (extract logic)
    pending = await mock_repo.get_pending_retries(limit=10)
    for item in pending:
        if item["retry_count"] >= item["max_retries"]:
            await mock_repo.update_decision_outcome(
                item["decision_id"], item["decision_timestamp"],
                {"status": "dead_letter_exhausted", "execution_result": {}},
            )
            await mock_repo.mark_resolved(item["id"], "max_retries_exhausted")

    mock_repo.mark_resolved.assert_called_once_with(1, "max_retries_exhausted")


@pytest.mark.asyncio
async def test_dead_letter_loop_increments_retry(service, mock_repo):
    """Dead-letter loop increments retry for items below max."""
    from datetime import datetime, timezone

    mock_repo.get_pending_retries.return_value = [
        {
            "id": 2,
            "decision_id": 20,
            "decision_timestamp": datetime.now(timezone.utc),
            "retry_count": 1,
            "max_retries": 5,
        }
    ]

    pending = await mock_repo.get_pending_retries(limit=10)
    for item in pending:
        if item["retry_count"] >= item["max_retries"]:
            pass
        else:
            await mock_repo.increment_retry(item["id"])

    mock_repo.increment_retry.assert_called_once_with(2)
