"""Tests for emergency close state persistence across restarts."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_task import AIManagerTask


@pytest.fixture
def mock_service():
    svc = MagicMock()
    svc._degradation = MagicMock()
    svc._degradation.get_tier.return_value = 0
    svc._circuit_breaker = MagicMock()
    svc._circuit_breaker.is_tripped.return_value = False
    svc._circuit_breaker.record_outcome = AsyncMock()
    svc._llm_scheduler = MagicMock()
    svc._lock_registry = MagicMock()
    svc._repo = MagicMock()
    svc._repo.upsert_state = AsyncMock(return_value={})
    svc._repo.update_heartbeat = AsyncMock()
    svc._hmac_key = "test-key"
    svc._close_positions_service = MagicMock()
    svc._close_positions_service.close_all_for_rule = AsyncMock(return_value={"total": 1, "closed": 1, "failed": 0})
    svc._market_data_cache = None
    svc._memory = None
    svc.emit_event = AsyncMock()
    svc._repo.insert_decision = AsyncMock(return_value=(1, datetime.now(timezone.utc)))
    svc._repo.record_realized_loss = AsyncMock(return_value={"realized_loss_today": 5.0})
    svc._repo.get_state = AsyncMock(return_value={"equity_at_day_start": 1000.0})
    svc._repo.init_equity_at_day_start = AsyncMock()
    return svc


@pytest.fixture
def task(mock_service):
    config = AIManagerConfig(emergency_close_enabled=True, emergency_equity_drop_pct=10.0, emergency_pnl_velocity_pct=5.0)
    stub_graph = MagicMock()
    t = AIManagerTask("acc1", mock_service, config, stub_graph)
    return t


class TestRestoreEmergencyState:
    def test_restore_ref_equity(self, task):
        state = {"emergency_ref_equity": 5000.0, "emergency_cooldown_until": None, "emergency_closed_symbols": None}
        task._restore_emergency_state(state)
        assert task._ws_buffer.get("_emergency_ref_equity") == 5000.0

    def test_restore_cooldown_still_active(self, task):
        future = datetime.now(timezone.utc) + timedelta(seconds=15)
        state = {"emergency_ref_equity": None, "emergency_cooldown_until": future, "emergency_closed_symbols": None}
        task._restore_emergency_state(state)
        assert task._emergency_cooldown_until > time.monotonic()

    def test_restore_cooldown_expired(self, task):
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        state = {"emergency_ref_equity": None, "emergency_cooldown_until": past, "emergency_closed_symbols": None}
        task._restore_emergency_state(state)
        assert task._emergency_cooldown_until == 0.0

    def test_restore_closed_symbols_active(self, task):
        recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        state = {"emergency_ref_equity": None, "emergency_cooldown_until": None, "emergency_closed_symbols": {"BTCUSDT": recent}}
        task._restore_emergency_state(state)
        assert "BTCUSDT" in task._emergency_closed_symbols
        age = time.monotonic() - task._emergency_closed_symbols["BTCUSDT"]
        assert 9.0 <= age <= 12.0

    def test_restore_closed_symbols_expired(self, task):
        old = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        state = {"emergency_ref_equity": None, "emergency_cooldown_until": None, "emergency_closed_symbols": {"BTCUSDT": old}}
        task._restore_emergency_state(state)
        assert "BTCUSDT" not in task._emergency_closed_symbols

    def test_restore_closed_symbols_from_json_string(self, task):
        import json
        recent = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        state = {"emergency_ref_equity": None, "emergency_cooldown_until": None, "emergency_closed_symbols": json.dumps({"ETHUSDT": recent})}
        task._restore_emergency_state(state)
        assert "ETHUSDT" in task._emergency_closed_symbols

    def test_restore_empty_state(self, task):
        state = {"emergency_ref_equity": None, "emergency_cooldown_until": None, "emergency_closed_symbols": None}
        task._restore_emergency_state(state)
        assert task._ws_buffer.get("_emergency_ref_equity") is None
        assert task._emergency_cooldown_until == 0.0
        assert task._emergency_closed_symbols == {}


class TestPersistEmergencyState:
    @pytest.mark.asyncio
    async def test_persist_after_emergency_close(self, task, mock_service):
        task._ws_buffer["_emergency_ref_equity"] = 5000.0
        task._emergency_cooldown_until = time.monotonic() + 25.0
        task._emergency_closed_symbols = {"BTCUSDT": time.monotonic() - 5.0}

        await task._persist_emergency_state()

        mock_service._repo.upsert_state.assert_called_once()
        call_kwargs = mock_service._repo.upsert_state.call_args[1]
        assert call_kwargs["emergency_ref_equity"] == 5000.0
        assert call_kwargs["emergency_cooldown_until"] is not None
        closed = call_kwargs["emergency_closed_symbols"]
        assert "BTCUSDT" in closed

    @pytest.mark.asyncio
    async def test_persist_skips_expired_symbols(self, task, mock_service):
        task._ws_buffer["_emergency_ref_equity"] = None
        task._emergency_cooldown_until = 0.0
        task._emergency_closed_symbols = {"OLDCOIN": time.monotonic() - 60.0}

        await task._persist_emergency_state()

        call_kwargs = mock_service._repo.upsert_state.call_args[1]
        import json
        symbols = json.loads(call_kwargs["emergency_closed_symbols"])
        assert "OLDCOIN" not in symbols

    @pytest.mark.asyncio
    async def test_persist_no_cooldown_when_expired(self, task, mock_service):
        task._emergency_cooldown_until = time.monotonic() - 10.0

        await task._persist_emergency_state()

        call_kwargs = mock_service._repo.upsert_state.call_args[1]
        assert call_kwargs["emergency_cooldown_until"] is None


class TestDryRunBlocksEmergency:
    @pytest.mark.asyncio
    async def test_dry_run_prevents_emergency_close(self, mock_service):
        config = AIManagerConfig(emergency_close_enabled=True, dry_run=True)
        stub_graph = MagicMock()
        t = AIManagerTask("acc1", mock_service, config, stub_graph)
        t._ws_buffer = {
            "positions": [{"symbol": "BTCUSDT", "side": "Buy", "unrealisedPnl": "-500"}],
            "equity": "4000",
            "_emergency_ref_equity": 5000.0,
        }
        result = await t._check_emergency_close()
        assert result is False
        mock_service._close_positions_service.close_all_for_rule.assert_not_called()
