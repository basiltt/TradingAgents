"""Tests for sweep defense state machine."""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_task():
    task = MagicMock()
    task._account_id = "test-account"
    task._config = MagicMock()
    task._config.sweep_recovery_timeout_candles = 3
    task._config.sweep_confidence_threshold = 0.5
    task._sweep_state = {}
    task._sweep_original_sl = {}
    task._sweep_defense_started_at = {}
    task._sweep_blocked_symbols = set()
    task._is_hedge_mode = False
    task._service = MagicMock()
    task._service._repo = MagicMock()
    task._service._repo.update_sweep_state = AsyncMock()
    task._service._repo.insert_sweep_event = AsyncMock()
    task._modify_stop_loss = AsyncMock(return_value=True)
    task._persist_sweep_state = AsyncMock()
    task._ws_buffer = {"positions": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}]}
    return task


class TestSweepStateMachine:
    @pytest.mark.asyncio
    async def test_transition_to_defending(self, mock_task):
        from backend.services.ai_manager_task import AIManagerTask
        sweep_signal = {"confidence": 0.8, "direction": "long_hunt", "targets_my_position": True}
        await AIManagerTask._handle_sweep_detected(mock_task, "BTCUSDT", sweep_signal, current_sl=67000.0)
        assert mock_task._sweep_state["BTCUSDT"] == "DEFENDING"
        assert mock_task._sweep_original_sl["BTCUSDT"] == 67000.0
        assert "BTCUSDT" in mock_task._sweep_blocked_symbols

    @pytest.mark.asyncio
    async def test_transition_to_resolved(self, mock_task):
        from backend.services.ai_manager_task import AIManagerTask
        mock_task._sweep_state["BTCUSDT"] = "DEFENDING"
        mock_task._sweep_original_sl["BTCUSDT"] = 67000.0
        mock_task._sweep_blocked_symbols.add("BTCUSDT")

        await AIManagerTask._handle_sweep_resolved(mock_task, "BTCUSDT")
        assert mock_task._sweep_state.get("BTCUSDT") is None
        assert "BTCUSDT" not in mock_task._sweep_blocked_symbols
        mock_task._modify_stop_loss.assert_called_with("BTCUSDT", 67000.0)

    @pytest.mark.asyncio
    async def test_transition_to_timeout(self, mock_task):
        from backend.services.ai_manager_task import AIManagerTask
        mock_task._sweep_state["BTCUSDT"] = "DEFENDING"
        mock_task._sweep_defense_started_at["BTCUSDT"] = time.time() - 1000
        mock_task._sweep_original_sl["BTCUSDT"] = 67000.0
        mock_task._sweep_blocked_symbols.add("BTCUSDT")
        mock_task._config.sweep_recovery_timeout_candles = 3

        await AIManagerTask._check_sweep_timeout(mock_task, "BTCUSDT")
        assert "BTCUSDT" not in mock_task._sweep_blocked_symbols

    @pytest.mark.asyncio
    async def test_db_persistence_on_transition(self, mock_task):
        from backend.services.ai_manager_task import AIManagerTask
        sweep_signal = {"confidence": 0.8, "direction": "long_hunt", "targets_my_position": True}
        await AIManagerTask._handle_sweep_detected(mock_task, "BTCUSDT", sweep_signal, current_sl=67000.0)
        # _persist_sweep_state is mocked on mock_task, so verify it was called
        mock_task._persist_sweep_state.assert_called()
        mock_task._service._repo.insert_sweep_event.assert_called()
