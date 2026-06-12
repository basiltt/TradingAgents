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


@pytest.mark.asyncio
async def test_persist_false_override_survives_respawn(service, mock_repo):
    """A health-sweep / kill-switch respawn (no explicit override arg) must re-apply
    the per-scan capability toggles onto the CURRENT DB config — preserving the
    capability selection while picking up fresh values for everything else."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        inst = MagicMock()
        inst.start = MagicMock()
        MockTask.return_value = inst

        # enable with a non-persisting override (emergency_close OFF, trailing ON)
        cfg = AIManagerConfig(
            auto_enabled=True, emergency_close_enabled=False, trailing_enabled=True
        )
        await service.enable("acc-1", cfg, persist=False)
        assert "acc-1" in service._ephemeral_capability_overrides

        # Between enable and respawn, the user locks a position (written to DB).
        # The DB config now carries locked_positions=["BTCUSDT"]. A respawn must use
        # this FRESH value (R2-1: no stale snapshot), while re-applying the toggles.
        import json as _json
        mock_repo.get_state = AsyncMock(return_value={
            "enabled": True, "fsm_state": "sleeping",
            "config": _json.dumps({"locked_positions": ["BTCUSDT"]}),
            "circuit_breaker_count": 0, "circuit_breaker_active": False,
        })

        # Simulate a respawn with NO override arg (how the health-sweep loop calls it).
        MockTask.reset_mock()
        await service._spawn_task("acc-1")

        spawned = MockTask.call_args.kwargs["config"]
        assert spawned.emergency_close_enabled is False  # capability toggle preserved
        assert spawned.trailing_enabled is True           # capability toggle preserved
        assert spawned.locked_positions == ["BTCUSDT"]    # fresh DB value, not stale snapshot


@pytest.mark.asyncio
async def test_persisting_enable_clears_ephemeral_override(service, mock_repo):
    """A later persisting enable() supersedes a prior ephemeral override."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        MockTask.return_value = MagicMock(start=MagicMock())
        await service.enable("acc-1", AIManagerConfig(auto_enabled=True, mtf_enabled=False), persist=False)
        assert "acc-1" in service._ephemeral_capability_overrides

        await service.enable("acc-1", AIManagerConfig(auto_enabled=True), persist=True)
        assert "acc-1" not in service._ephemeral_capability_overrides


@pytest.mark.asyncio
async def test_disable_clears_ephemeral_override(service, mock_repo):
    """disable() must drop the ephemeral override so a later re-enable starts clean."""
    mock_repo.upsert_state = AsyncMock()
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        MockTask.return_value = MagicMock(start=MagicMock())
        await service.enable("acc-1", AIManagerConfig(auto_enabled=True, mtf_enabled=False), persist=False)
        assert "acc-1" in service._ephemeral_capability_overrides

        await service.disable("acc-1")
        assert "acc-1" not in service._ephemeral_capability_overrides


@pytest.mark.asyncio
async def test_patch_config_capability_clears_ephemeral_override(service, mock_repo):
    """A persisting patch_config of a capability flag must drop the ephemeral override
    so it doesn't re-apply (revert the edit) on the next respawn."""
    mock_repo.sync_config_columns = AsyncMock()
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        MockTask.return_value = MagicMock(start=MagicMock(), reload_config=MagicMock())
        await service.enable(
            "acc-1", AIManagerConfig(auto_enabled=True, mtf_enabled=False), persist=False
        )
        assert "acc-1" in service._ephemeral_capability_overrides

        # Operator edits the same capability via the persisting dashboard path.
        await service.patch_config("acc-1", {"mtf_enabled": True})
        assert "acc-1" not in service._ephemeral_capability_overrides


@pytest.mark.asyncio
async def test_patch_config_non_capability_keeps_ephemeral_override(service, mock_repo):
    """Patching a NON-capability field must NOT clear the per-scan capability override."""
    mock_repo.sync_config_columns = AsyncMock()
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        MockTask.return_value = MagicMock(start=MagicMock(), reload_config=MagicMock())
        await service.enable(
            "acc-1", AIManagerConfig(auto_enabled=True, mtf_enabled=False), persist=False
        )
        await service.patch_config("acc-1", {"max_daily_actions": 12})
        assert "acc-1" in service._ephemeral_capability_overrides


@pytest.mark.asyncio
async def test_lock_position_reload_preserves_active_capability_override(service, mock_repo):
    """While a per-scan override is active, a non-capability edit (lock_position) must
    reload the live task WITH the override still applied — not transiently revert to
    DB capability values."""
    mock_repo.sync_config_columns = AsyncMock()
    # DB config carries default capabilities (emergency_close ON).
    mock_repo.get_state = AsyncMock(return_value={
        "enabled": True, "fsm_state": "sleeping", "config": "{}",
        "circuit_breaker_count": 0, "circuit_breaker_active": False,
    })
    reloaded = {}
    live = MagicMock()
    live.is_dead = MagicMock(return_value=False)
    live._config = AIManagerConfig(auto_enabled=False)
    live.reload_config = MagicMock(side_effect=lambda c: reloaded.update(cfg=c))
    service._tasks["acc-1"] = live

    # Active per-scan override turns emergency_close OFF (in-memory only).
    await service.enable(
        "acc-1", AIManagerConfig(auto_enabled=True, emergency_close_enabled=False), persist=False
    )
    # Operator locks a position (non-capability edit). The live reload must keep
    # emergency_close OFF (the override), not flip it back ON from DB.
    await service.lock_position("acc-1", "BTCUSDT")
    assert reloaded["cfg"].emergency_close_enabled is False
    assert reloaded["cfg"].locked_positions == ["BTCUSDT"]
