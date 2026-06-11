"""enable(persist=False) must spawn/reload with the given config but NOT write it to DB."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai_manager_schemas import AIManagerConfig


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.upsert_state = AsyncMock(return_value={})
    repo.sync_config_columns = AsyncMock()
    repo.insert_log = AsyncMock()
    repo.get_state = AsyncMock(return_value={
        "enabled": True, "fsm_state": "sleeping", "config": "{}",
        "circuit_breaker_count": 0, "circuit_breaker_active": False,
    })
    return repo


@pytest.fixture
def service(mock_repo):
    from backend.services.ai_account_manager_service import AIAccountManagerService
    from backend.services.ai_manager_llm_scheduler import PriorityLLMScheduler
    from backend.services.position_lock_registry import PositionLockRegistry

    return AIAccountManagerService(
        accounts_service=MagicMock(),
        close_positions_service=MagicMock(),
        ws_manager=None,
        ai_manager_repo=mock_repo,
        market_data_cache=MagicMock(),
        position_lock_registry=PositionLockRegistry(),
        llm_scheduler=PriorityLLMScheduler(),
        hmac_key="test-key",
    )


@pytest.mark.asyncio
async def test_enable_persist_false_skips_config_write_on_spawn(service, mock_repo):
    """Fresh spawn with persist=False must NOT call sync_config_columns."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        inst = MagicMock()
        inst.start = MagicMock()
        MockTask.return_value = inst
        cfg = AIManagerConfig(auto_enabled=True, trailing_enabled=True)

        await service.enable("acc-1", cfg, persist=False)

        mock_repo.sync_config_columns.assert_not_called()
        # Task spawned with the override config (not the empty DB config)
        assert MockTask.call_args.kwargs["config"].trailing_enabled is True


@pytest.mark.asyncio
async def test_enable_persist_true_writes_config_on_spawn(service, mock_repo):
    """Default persist=True preserves existing behavior (writes config)."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        inst = MagicMock()
        inst.start = MagicMock()
        MockTask.return_value = inst

        await service.enable("acc-1", AIManagerConfig(auto_enabled=True))

        mock_repo.sync_config_columns.assert_called_once()


@pytest.mark.asyncio
async def test_enable_persist_false_alive_task_reloads_without_write(service, mock_repo):
    """Alive task: reload_config in-memory, no DB write when persist=False."""
    alive = MagicMock()
    alive.is_dead = MagicMock(return_value=False)
    alive._config = AIManagerConfig(auto_enabled=False)
    alive.reload_config = MagicMock()
    service._tasks["acc-1"] = alive

    cfg = AIManagerConfig(auto_enabled=True, mtf_enabled=False)
    await service.enable("acc-1", cfg, persist=False)

    alive.reload_config.assert_called_once()
    assert alive.reload_config.call_args.args[0].mtf_enabled is False
    mock_repo.sync_config_columns.assert_not_called()
