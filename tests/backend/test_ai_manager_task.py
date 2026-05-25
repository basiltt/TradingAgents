"""Tests for AIManagerTask — Phase 2 Task 2.4."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai_manager_schemas import AIManagerConfig


@pytest.fixture
def mock_service():
    svc = MagicMock()
    svc._degradation = MagicMock()
    svc._degradation.get_tier.return_value = 0
    svc._degradation.check_health = AsyncMock()
    svc._circuit_breaker = MagicMock()
    svc._circuit_breaker.is_tripped.return_value = False
    svc._circuit_breaker.record_outcome = AsyncMock()
    svc._llm_scheduler = MagicMock()
    svc._lock_registry = MagicMock()
    svc._lock_registry.acquire = AsyncMock(return_value=True)
    svc._lock_registry.release = MagicMock()
    svc._repo = MagicMock()
    from datetime import datetime, timezone
    svc._repo.insert_decision = AsyncMock(return_value=(1, datetime.now(timezone.utc)))
    svc._repo.update_decision_outcome = AsyncMock()
    svc._repo.insert_failed_outcome = AsyncMock()
    svc._repo.record_realized_loss = AsyncMock()
    svc._repo.increment_actions_atomic = AsyncMock(return_value=True)
    svc._repo.is_kill_switch_active = AsyncMock(return_value=False)
    svc._repo.update_heartbeat = AsyncMock()
    svc._hmac_key = "test-hmac-key"
    svc._close_positions_service = MagicMock()
    svc._close_positions_service.close_position = AsyncMock(return_value={"realized_pnl": -5.0})
    return svc


@pytest.fixture
def stub_graph():
    g = MagicMock()
    g.ainvoke = AsyncMock(return_value={"action": "HOLD", "reason": "no_signal"})
    return g


@pytest.fixture
def task(mock_service, stub_graph):
    from backend.services.ai_manager_task import AIManagerTask

    # Make llm_scheduler.slot() an async context manager
    slot_cm = MagicMock()
    slot_cm.__aenter__ = AsyncMock(return_value=None)
    slot_cm.__aexit__ = AsyncMock(return_value=False)
    mock_service._llm_scheduler.slot.return_value = slot_cm

    return AIManagerTask(
        account_id="acc-1",
        service=mock_service,
        config=AIManagerConfig(),
        compiled_graph=stub_graph,
    )


@pytest.mark.asyncio
async def test_initial_state_is_sleeping(task):
    assert task.state == "sleeping"


@pytest.mark.asyncio
async def test_start_creates_asyncio_task(task):
    task.start()
    assert task._task is not None
    task.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_ws_event_transitions_to_monitoring(task):
    await task.on_ws_event({"positions": [{"symbol": "BTCUSDT"}]})
    assert task.state == "monitoring"


@pytest.mark.asyncio
async def test_ws_event_no_positions_stays_sleeping(task):
    await task.on_ws_event({"positions": []})
    assert task.state == "sleeping"


@pytest.mark.asyncio
async def test_pause_and_resume(task):
    task.pause()
    assert task.state == "paused"
    task.resume()
    assert task.state == "sleeping"


@pytest.mark.asyncio
async def test_cancel_sets_event(task):
    task.cancel()
    assert task._cancel_event.is_set()


@pytest.mark.asyncio
async def test_is_dead_when_task_done(task):
    task.start()
    task.cancel()
    await asyncio.sleep(0.05)
    assert task.is_dead()


@pytest.mark.asyncio
async def test_evaluate_hold_stays_monitoring(task, stub_graph):
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    assert task.state == "monitoring"


@pytest.mark.asyncio
async def test_evaluate_close_executes(task, stub_graph, mock_service):
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "reversal",
        "confidence": 0.9,
        "timestamp": 123,
    }
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    assert task.state == "monitoring"
    mock_service._close_positions_service.close_position.assert_called_once()
    mock_service._circuit_breaker.record_outcome.assert_called_once()


@pytest.mark.asyncio
async def test_circuit_breaker_tripped_skips_eval(task, mock_service, stub_graph):
    mock_service._circuit_breaker.is_tripped.return_value = True
    mock_service._circuit_breaker.check_cooldown = AsyncMock(return_value=False)
    task._state = "monitoring"
    await task._evaluate()
    assert task.state == "monitoring"
    stub_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_degradation_tier_3_skips_eval(task, mock_service, stub_graph):
    mock_service._degradation.get_tier.return_value = 3
    task._state = "monitoring"
    await task._evaluate()
    assert task.state == "monitoring"
    stub_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_kill_switch_blocks_execution(task, mock_service, stub_graph):
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
        "timestamp": 1,
    }
    mock_service._repo.is_kill_switch_active.return_value = True
    task._state = "monitoring"
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_reload_config(task):
    new_config = AIManagerConfig(evaluation_interval_s=30)
    task.reload_config(new_config)
    assert task._config.evaluation_interval_s == 30


@pytest.mark.asyncio
async def test_execution_exception_records_dead_letter(task, stub_graph, mock_service):
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "reversal",
        "confidence": 0.85,
    }
    mock_service._close_positions_service.close_position.side_effect = Exception("exchange timeout")
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    assert task.state == "monitoring"
    mock_service._repo.insert_failed_outcome.assert_called_once()
    mock_service._lock_registry.release.assert_called_once()


@pytest.mark.asyncio
async def test_lock_always_released_on_success(task, stub_graph, mock_service):
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "reversal",
        "confidence": 0.85,
    }
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._lock_registry.release.assert_called_once_with("acc-1", "BTCUSDT")


@pytest.mark.asyncio
async def test_loss_accounting_on_negative_pnl(task, stub_graph, mock_service):
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "stop_loss",
        "confidence": 0.9,
    }
    mock_service._close_positions_service.close_position.return_value = {"realized_pnl": -10.0}
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._repo.record_realized_loss.assert_called_once_with("acc-1", 10.0)


@pytest.mark.asyncio
async def test_budget_exhausted_blocks_execution(task, stub_graph, mock_service):
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.8,
    }
    mock_service._repo.increment_actions_atomic.return_value = False
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()
    mock_service._lock_registry.release.assert_called_once()


@pytest.mark.asyncio
async def test_dry_run_blocks_execution(task, stub_graph, mock_service):
    """dry_run=True should log but never call close_position."""
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "reversal",
        "confidence": 0.9,
    }
    task._config = AIManagerConfig(dry_run=True)
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()
    mock_service._repo.insert_decision.assert_not_called()


@pytest.mark.asyncio
async def test_positions_none_safe(task):
    """ws_event with positions=None must not crash."""
    await task.on_ws_event({"positions": None, "wallet": {}})
    assert task.state == "sleeping"


@pytest.mark.asyncio
async def test_half_open_hold_resets_flag_no_restart(task, stub_graph, mock_service):
    """On HOLD during half-open, reset half_open_used but don't restart cooldown."""
    mock_service._circuit_breaker.is_tripped.return_value = True
    mock_service._circuit_breaker.check_cooldown = AsyncMock(return_value=True)
    mock_service._repo.upsert_state = AsyncMock()

    stub_graph.ainvoke.return_value = {"action": "HOLD", "reason": "no_signal"}
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()

    # half_open_used reset
    mock_service._repo.upsert_state.assert_called_with(
        "acc-1", circuit_breaker_half_open_used=False
    )
    # restart_cooldown NOT called
    mock_service._circuit_breaker.restart_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_half_open_slot_unavailable_resets_flag(task, stub_graph, mock_service):
    """Slot-unavailable during half-open resets flag, no restart_cooldown."""
    mock_service._circuit_breaker.is_tripped.return_value = True
    mock_service._circuit_breaker.check_cooldown = AsyncMock(return_value=True)
    mock_service._repo.upsert_state = AsyncMock()

    # Make slot() raise RuntimeError with "slot not available"
    slot_cm = MagicMock()
    slot_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("LLM slot not available for acc-1"))
    slot_cm.__aexit__ = AsyncMock(return_value=False)
    mock_service._llm_scheduler.slot.return_value = slot_cm

    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()

    mock_service._repo.upsert_state.assert_called_with(
        "acc-1", circuit_breaker_half_open_used=False
    )
    mock_service._circuit_breaker.restart_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_half_open_execution_negative_pnl_resets_and_restarts(task, stub_graph, mock_service):
    """After execution with negative PnL during half-open, reset flag + restart cooldown."""
    mock_service._circuit_breaker.is_tripped.return_value = True
    mock_service._circuit_breaker.check_cooldown = AsyncMock(return_value=True)
    mock_service._repo.upsert_state = AsyncMock()
    mock_service._close_positions_service.close_position.return_value = {"realized_pnl": -5.0}

    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
    }
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()

    mock_service._repo.upsert_state.assert_called_with(
        "acc-1", circuit_breaker_half_open_used=False
    )
    mock_service._circuit_breaker.restart_cooldown.assert_called_once_with("acc-1")


@pytest.mark.asyncio
async def test_half_open_graph_exception_resets_and_restarts(task, stub_graph, mock_service):
    """Graph exception during half-open resets flag + restarts cooldown."""
    mock_service._circuit_breaker.is_tripped.return_value = True
    mock_service._circuit_breaker.check_cooldown = AsyncMock(return_value=True)
    mock_service._repo.upsert_state = AsyncMock()

    stub_graph.ainvoke.side_effect = Exception("LLM error")
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()

    mock_service._repo.upsert_state.assert_called_with(
        "acc-1", circuit_breaker_half_open_used=False
    )
    mock_service._circuit_breaker.restart_cooldown.assert_called_once_with("acc-1")


@pytest.mark.asyncio
async def test_ainvoke_timeout_triggers_degradation(task, stub_graph, mock_service):
    """Graph timeout should fire degradation check with 'timeout'."""
    stub_graph.ainvoke.side_effect = asyncio.TimeoutError()
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()

    mock_service._degradation.check_health.assert_called_with("timeout")
    assert task.state == "monitoring"


@pytest.mark.asyncio
async def test_confidence_below_threshold_skips_execution(task, stub_graph, mock_service):
    """Actions below confidence threshold should not execute."""
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "weak",
        "confidence": 0.3,
    }
    task._config = AIManagerConfig(confidence_threshold=0.7)
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_excluded_symbol_skips_execution(task, stub_graph, mock_service):
    """Excluded symbols should not execute."""
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
    }
    task._config = AIManagerConfig(excluded_symbols=["BTCUSDT"])
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_symbol_cooldown_prevents_rapid_eval(task, stub_graph, mock_service):
    """Same symbol within 15s cooldown should not re-execute."""
    import time as _time

    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
    }
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    # First eval succeeds
    await task._evaluate()
    assert mock_service._close_positions_service.close_position.call_count == 1

    # Second eval within cooldown is blocked
    task._state = "monitoring"
    await task._evaluate()
    assert mock_service._close_positions_service.close_position.call_count == 1


@pytest.mark.asyncio
async def test_hold_fires_indeterminate_degradation(task, stub_graph, mock_service):
    """HOLD result should fire degradation check with 'indeterminate'."""
    stub_graph.ainvoke.return_value = {"action": "HOLD", "reason": "no_signal"}
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._degradation.check_health.assert_called_with("indeterminate")


@pytest.mark.asyncio
async def test_hmac_key_missing_blocks_execution(task, stub_graph, mock_service):
    """Empty HMAC key should block execution after lock acquired."""
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
    }
    mock_service._hmac_key = ""
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()
    mock_service._lock_registry.release.assert_called_once()


@pytest.mark.asyncio
async def test_resume_with_open_positions_goes_to_monitoring(task):
    """Resume should transition to MONITORING when positions exist."""
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    task.pause()
    assert task.state == "paused"
    task.resume()
    assert task.state == "monitoring"


@pytest.mark.asyncio
async def test_lock_acquire_fails_skips_execution(task, stub_graph, mock_service):
    """Position lock timeout should prevent any execution."""
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
    }
    mock_service._lock_registry.acquire.return_value = False
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._repo.insert_decision.assert_not_called()
    mock_service._close_positions_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_ws_event_filters_unknown_keys(task):
    """Unknown keys in ws_event data should be dropped."""
    await task.on_ws_event({
        "positions": [{"symbol": "X"}],
        "rogue_key": 123,
        "wallet": {"balance": 100},
    })
    assert "rogue_key" not in task._ws_buffer
    assert "positions" in task._ws_buffer
    assert "wallet" in task._ws_buffer


@pytest.mark.asyncio
async def test_slot_unavailable_normal_flow(task, stub_graph, mock_service):
    """Slot unavailable without half-open: state stays monitoring, no execution."""
    slot_cm = MagicMock()
    slot_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("LLM slot not available"))
    slot_cm.__aexit__ = AsyncMock(return_value=False)
    mock_service._llm_scheduler.slot.return_value = slot_cm

    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    assert task.state == "monitoring"
    mock_service._close_positions_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_set_killed_stops_running_task(task):
    """set_killed causes the running task loop to exit."""
    task.start()
    await asyncio.sleep(0.02)
    task.set_killed()
    # set_killed sets _cancel_event and calls task.cancel() which cancels the asyncio.Task
    try:
        await asyncio.wait_for(task._task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert task._killed is True
    assert task._task.done()


@pytest.mark.asyncio
async def test_budget_exception_still_releases_lock(task, stub_graph, mock_service):
    """If increment_actions_atomic raises, lock must still be released."""
    stub_graph.ainvoke.return_value = {
        "action": "FULL_CLOSE",
        "symbol": "BTCUSDT",
        "reason": "test",
        "confidence": 0.9,
    }
    mock_service._repo.increment_actions_atomic.side_effect = Exception("DB error")
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    await task._evaluate()
    mock_service._close_positions_service.close_position.assert_not_called()
    mock_service._lock_registry.release.assert_called_once()
