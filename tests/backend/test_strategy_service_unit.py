"""Unit tests for StrategyService — covers CRUD, serialization, import."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.strategy_service import StrategyService


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def svc(db):
    return StrategyService(db=db)


class TestCreateStrategy:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_returns_strategy_with_id(self, svc, db):
        db.insert_strategy = AsyncMock()
        result = await svc.create_strategy({
            "name": "Momentum", "description": "desc",
            "category": "trend", "status": "active", "config": {},
        })
        assert "id" in result
        assert result["name"] == "Momentum"
        assert result["created_at"] is not None
        db.insert_strategy.assert_awaited_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_sets_timestamps(self, svc, db):
        db.insert_strategy = AsyncMock()
        result = await svc.create_strategy({
            "name": "S", "description": "d",
            "category": "c", "status": "active", "config": {},
        })
        assert result["created_at"] == result["updated_at"]


class TestListStrategies:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_list_returns_serialized(self, svc, db):
        db.list_strategies = AsyncMock(return_value=[
            {"id": "1", "name": "A", "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "updated_at": "2024-01-01"},
        ])
        result = await svc.list_strategies()
        assert len(result) == 1
        assert isinstance(result[0]["created_at"], str)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_list_passes_filters(self, svc, db):
        db.list_strategies = AsyncMock(return_value=[])
        await svc.list_strategies(status="active", category="trend")
        db.list_strategies.assert_awaited_once_with(status="active", category="trend")


class TestGetStrategy:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_returns_strategy(self, svc, db):
        db.get_strategy = AsyncMock(return_value={"id": "1", "name": "A"})
        result = await svc.get_strategy("1")
        assert result["id"] == "1"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_returns_none_not_found(self, svc, db):
        db.get_strategy = AsyncMock(return_value=None)
        assert await svc.get_strategy("missing") is None


class TestUpdateStrategy:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_empty_data_returns_existing(self, svc, db):
        db.get_strategy = AsyncMock(return_value={"id": "1", "name": "A"})
        result = await svc.update_strategy("1", {})
        assert result["id"] == "1"
        db.update_strategy.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_returns_none_when_not_found(self, svc, db):
        db.update_strategy = AsyncMock(return_value=False)
        result = await svc.update_strategy("1", {"name": "B"})
        assert result is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_success(self, svc, db):
        db.update_strategy = AsyncMock(return_value=True)
        db.get_strategy = AsyncMock(return_value={"id": "1", "name": "B"})
        result = await svc.update_strategy("1", {"name": "B"})
        assert result["name"] == "B"


class TestDeleteStrategy:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_success(self, svc, db):
        db.delete_strategy = AsyncMock(return_value=True)
        assert await svc.delete_strategy("1") is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_not_found(self, svc, db):
        db.delete_strategy = AsyncMock(return_value=False)
        assert await svc.delete_strategy("missing") is False


class TestImportStrategies:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_import_strips_ids_and_creates(self, svc, db):
        db.insert_strategy = AsyncMock()
        result = await svc.import_strategies([
            {"id": "old", "created_at": "old", "updated_at": "old",
             "name": "S1", "description": "d", "category": "c", "status": "active", "config": {}},
        ])
        assert len(result) == 1
        assert result[0]["id"] != "old"
        assert "created_at" in result[0]


class TestSerializeDatetimes:
    def test_serializes_datetime_objects(self, svc):
        d = {"created_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "updated_at": "already-string"}
        result = svc._serialize_datetimes(d)
        assert isinstance(result["created_at"], str)
        assert result["updated_at"] == "already-string"

    def test_skips_none(self, svc):
        d = {"created_at": None, "updated_at": None}
        result = svc._serialize_datetimes(d)
        assert result["created_at"] is None
