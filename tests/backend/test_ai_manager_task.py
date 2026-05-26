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
    svc._repo.record_realized_loss = AsyncMock(return_value={"realized_loss_today": 10.0, "equity_at_day_start": 1000.0})
    svc._repo.record_realized_profit = AsyncMock(return_value={"realized_profit_today": 5.0, "equity_at_day_start": 1000.0})
    svc._repo.increment_actions_atomic = AsyncMock(return_value=True)
    svc._repo.increment_token_budget_atomic = AsyncMock(return_value=True)
    svc._repo.is_kill_switch_active = AsyncMock(return_value=False)
    svc._repo.get_state = AsyncMock(return_value={"equity_at_day_start": 1000.0})
    svc._repo.init_equity_at_day_start = AsyncMock()
    svc._repo.set_kill_switch = AsyncMock()
    svc._repo.update_heartbeat = AsyncMock()
    svc._hmac_key = "test-hmac-key"
    svc._close_positions_service = MagicMock()
    svc._close_positions_service.close_all_for_rule = AsyncMock(return_value={"total": 1, "closed": 1, "failed": 0, "results": [{"realized_pnl": -5.0}]})
    svc._memory = None
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
    await task.on_ws_event({"type": "position_update", "data": {"symbol": "BTCUSDT", "size": "0.1"}})
    assert task.state == "monitoring"


@pytest.mark.asyncio
async def test_ws_event_no_positions_stays_sleeping(task):
    await task.on_ws_event({"type": "position_update", "data": {"symbol": "BTCUSDT", "size": "0"}})
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
    mock_service._close_positions_service.close_all_for_rule.assert_called_once()
    mock_service._circuit_breaker.record_outcome.assert_called_once()


@pytest.mark.asyncio
async def test_circuit_breaker_tripped_skips_eval(task, mock_service, stub_graph):
    mock_service._circuit_breaker.is_tripped.return_value = True
    mock_service._circuit_breaker.check_cooldown = AsyncMock(return_value=False)
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]}
    await task._evaluate()
    assert task.state == "monitoring"
    stub_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_degradation_tier_3_skips_eval(task, mock_service, stub_graph):
    mock_service._degradation.get_tier.return_value = 3
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]}
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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()


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
    mock_service._close_positions_service.close_all_for_rule.side_effect = Exception("exchange timeout")
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
    mock_service._close_positions_service.close_all_for_rule.return_value = {"total": 1, "closed": 1, "failed": 0, "results": []}
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT", "unrealisedPnl": "-10.0"}]}
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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()
    mock_service._lock_registry.release.assert_called_once()


@pytest.mark.asyncio
async def test_dry_run_blocks_execution(task, stub_graph, mock_service):
    """dry_run=True should log but never call close_all_for_rule."""
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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()
    mock_service._repo.insert_decision.assert_not_called()


@pytest.mark.asyncio
async def test_positions_none_safe(task):
    """ws_event with missing/null data must not crash."""
    await task.on_ws_event({"type": "position_update", "data": {}})
    assert task.state == "sleeping"
    await task.on_ws_event({"type": "wallet_update", "data": {}})
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
    mock_service._close_positions_service.close_all_for_rule.return_value = {"total": 1, "closed": 1, "failed": 0, "results": [{"realized_pnl": -5.0}]}

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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()


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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()


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
    assert mock_service._close_positions_service.close_all_for_rule.call_count == 1

    # Second eval within cooldown is blocked
    task._state = "monitoring"
    await task._evaluate()
    assert mock_service._close_positions_service.close_all_for_rule.call_count == 1


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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()
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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()


@pytest.mark.asyncio
async def test_ws_event_ignores_unknown_event_types(task):
    """Unknown event types should not modify the buffer."""
    task._ws_buffer = {"positions": [{"symbol": "X"}]}
    await task.on_ws_event({"type": "unknown_type", "data": {"foo": "bar"}})
    assert task._ws_buffer == {"positions": [{"symbol": "X"}]}


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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()


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
    mock_service._close_positions_service.close_all_for_rule.assert_not_called()
    mock_service._lock_registry.release.assert_called_once()


# === _enforce_daily_limits tests ===


@pytest.mark.asyncio
async def test_daily_loss_cap_triggers_pause(task, mock_service):
    """When realized loss exceeds max_daily_loss_pct, task should pause."""
    mock_service._repo.record_realized_loss = AsyncMock(
        return_value={"realized_loss_today": 60.0}
    )
    mock_service._repo.get_state = AsyncMock(
        return_value={"equity_at_day_start": 1000.0}
    )
    task._config.max_daily_loss_pct = 5.0
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}

    await task._enforce_daily_limits(-10.0)
    assert task.state == "paused"


@pytest.mark.asyncio
async def test_kill_switch_triggered_on_extreme_loss(task, mock_service):
    """When realized+unrealized >= 2x max_daily_loss_pct, kill switch fires."""
    mock_service._repo.record_realized_loss = AsyncMock(
        return_value={"realized_loss_today": 40.0}
    )
    mock_service._repo.get_state = AsyncMock(
        return_value={"equity_at_day_start": 1000.0}
    )
    task._config.max_daily_loss_pct = 5.0
    # realized=40 (4%) < 5%, so won't pause on first check
    # unrealized=70, total=110 (11%) >= 10% (2x5%), triggers kill switch
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT", "unrealisedPnl": -70.0}]}

    await task._enforce_daily_limits(-10.0)
    mock_service._repo.set_kill_switch.assert_called_once_with("acc-1", True)
    assert task._killed is True


@pytest.mark.asyncio
async def test_profit_target_reached_transitions_to_sleeping(task, mock_service):
    """When realized profit >= target, state transitions to sleeping."""
    mock_service._repo.record_realized_profit = AsyncMock(
        return_value={"realized_profit_today": 100.0}
    )
    mock_service._repo.get_state = AsyncMock(
        return_value={"equity_at_day_start": 1000.0}
    )
    task._config.daily_profit_target_pct = 5.0
    task._state = "monitoring"

    await task._enforce_daily_limits(20.0)
    assert task.state == "sleeping"


@pytest.mark.asyncio
async def test_daily_limits_none_equity_skips_enforcement(task, mock_service):
    """When equity_at_day_start is None, enforcement is skipped."""
    mock_service._repo.get_state = AsyncMock(return_value={"equity_at_day_start": None})
    mock_service._repo.init_equity_at_day_start = AsyncMock(return_value=None)
    task._ws_buffer = {}
    task._state = "monitoring"

    await task._enforce_daily_limits(-50.0)
    assert task.state == "monitoring"
    mock_service._repo.set_kill_switch.assert_not_called()


# === _get_unrealized_loss tests ===


@pytest.mark.asyncio
async def test_unrealized_loss_malformed_data(task):
    """Malformed unrealisedPnl should be skipped without error."""
    task._ws_buffer = {"positions": [
        {"symbol": "A", "unrealisedPnl": "bad"},
        {"symbol": "B", "unrealisedPnl": None},
        {"symbol": "C", "unrealisedPnl": -5.0},
    ]}
    result = task._get_unrealized_loss()
    assert result == 5.0


# === _build_graph_state memory tests ===


@pytest.mark.asyncio
async def test_build_graph_state_memory_failure_defaults(task, mock_service):
    """When memory fetch raises, defaults to empty lists and count=100."""
    mock_memory = MagicMock()
    mock_memory.get_episodic_context = AsyncMock(side_effect=Exception("DB down"))
    mock_service._memory = mock_memory
    task._ws_buffer = {"positions": []}

    state = await task._build_graph_state()
    assert state["episodic_memory"] == []
    assert state["patterns"] == []
    assert state["decision_count"] == 100


@pytest.mark.asyncio
async def test_build_graph_state_memory_success(task, mock_service):
    """When memory is available, its data flows into graph state."""
    mock_memory = MagicMock()
    mock_memory.get_episodic_context = AsyncMock(return_value=[{"action": "HOLD"}])
    mock_memory.get_semantic_patterns = AsyncMock(return_value=[{"type": "reversal"}])
    mock_memory.get_decision_count = AsyncMock(return_value=42)
    mock_service._memory = mock_memory
    task._ws_buffer = {"positions": []}

    state = await task._build_graph_state()
    assert state["episodic_memory"] == [{"action": "HOLD"}]
    assert state["patterns"] == [{"type": "reversal"}]
    assert state["decision_count"] == 42


@pytest.mark.asyncio
async def test_enforce_daily_limits_exception_triggers_failsafe_pause(task, mock_service, stub_graph):
    """If _enforce_daily_limits raises, the fail-safe in _execute_action pauses the task."""
    mock_service._repo.get_state = AsyncMock(side_effect=Exception("DB down"))
    stub_graph.ainvoke = AsyncMock(return_value={"action": "FULL_CLOSE", "symbol": "BTCUSDT", "reason": "test", "confidence": 0.9})
    mock_service._close_positions_service.close_all_for_rule = AsyncMock(return_value={"total": 1, "closed": 1, "failed": 0, "results": [{"realized_pnl": -5.0}]})
    task._state = "monitoring"
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT"}]}
    task._config.confidence_threshold = 0.5

    await task._evaluate()
    assert task.state == "paused"


@pytest.mark.asyncio
async def test_pause_wakes_sleep_cycle(task):
    """Calling pause() wakes the sleep cycle immediately."""
    task._state = "sleeping"
    task._wake_event = MagicMock()
    task._pause_event = MagicMock()
    
    task.pause()
    
    task._wake_event.set.assert_called_once()
    task._pause_event.set.assert_called_once()
    assert task.state == "paused"
