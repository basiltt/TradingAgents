"""Tests for enhanced AI Manager persistence methods."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestSweepStatePersistence:
    @pytest.mark.asyncio
    async def test_get_sweep_state_empty(self):
        from backend.services.ai_manager_repository import AIManagerRepository
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"sweep_state": {}})
        repo = AIManagerRepository(pool)
        result = await repo.get_sweep_state("acc1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_update_sweep_state(self):
        from backend.services.ai_manager_repository import AIManagerRepository
        pool = MagicMock()
        pool.execute = AsyncMock()
        repo = AIManagerRepository(pool)
        await repo.update_sweep_state("acc1", {"BTCUSDT": {"state": "DEFENDING", "original_sl": 67000.0}})
        pool.execute.assert_called_once()
        call_args = pool.execute.call_args[0]
        assert "sweep_state" in call_args[0]


class TestRegimeHistoryPersistence:
    @pytest.mark.asyncio
    async def test_insert_regime_history(self):
        from backend.services.ai_manager_repository import AIManagerRepository
        pool = MagicMock()
        pool.execute = AsyncMock()
        repo = AIManagerRepository(pool)
        await repo.insert_regime_history("acc1", "BTCUSDT", "trending_up", 0.85, {"adx": 32.5})
        pool.execute.assert_called_once()


class TestCorrelationSnapshotPersistence:
    @pytest.mark.asyncio
    async def test_insert_correlation_snapshot(self):
        from backend.services.ai_manager_repository import AIManagerRepository
        pool = MagicMock()
        pool.execute = AsyncMock()
        repo = AIManagerRepository(pool)
        await repo.insert_correlation_snapshot(
            "acc1", 0.75, {"BTC-ETH": 0.9}, [["BTC", "ETH"]], 3
        )
        pool.execute.assert_called_once()


class TestSweepEventPersistence:
    @pytest.mark.asyncio
    async def test_insert_sweep_event(self):
        from backend.services.ai_manager_repository import AIManagerRepository
        pool = MagicMock()
        pool.execute = AsyncMock()
        repo = AIManagerRepository(pool)
        await repo.insert_sweep_event(
            "acc1", symbol="BTCUSDT", event_type="sweep_detected",
            confidence=0.85, direction="long", swept_level=67000.0,
            detail={"wick_pct": 1.2}
        )
        pool.execute.assert_called_once()


class TestOrderbookSnapshotPersistence:
    @pytest.mark.asyncio
    async def test_insert_orderbook_snapshot(self):
        from backend.services.ai_manager_repository import AIManagerRepository
        pool = MagicMock()
        pool.execute = AsyncMock()
        repo = AIManagerRepository(pool)
        await repo.insert_orderbook_snapshot(
            "acc1", "BTCUSDT", 1.3, 2.5, 0.8,
            [{"price": 67000, "size": 100}], [{"price": 67100, "size": 50}]
        )
        pool.execute.assert_called_once()
