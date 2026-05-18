"""Unit tests for TradeRepository — validation, state machine, metadata, pagination helpers."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.trade_repository import (
    ConcurrentModification,
    InvalidStatusTransition,
    TradeNotFound,
    TradeRepository,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    VALID_SIDES,
    VALID_CLOSE_REASONS,
    VALID_EVENT_TYPES,
    METADATA_ALLOWLIST,
    SORT_COLUMNS,
    SYMBOL_PATTERN,
    _MAX_METADATA_BYTES,
    _MAX_PAGE_SIZE,
)


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def repo(db):
    return TradeRepository(db=db)


class TestValidateMetadata:
    def test_empty_metadata_ok(self, repo):
        repo._validate_metadata({})

    def test_none_metadata_ok(self, repo):
        repo._validate_metadata(None)

    def test_valid_keys(self, repo):
        repo._validate_metadata({"error_code": "E1", "reason": "stop_loss"})

    def test_invalid_keys_raises(self, repo):
        with pytest.raises(ValueError, match="Invalid metadata keys"):
            repo._validate_metadata({"bad_key": "val"})

    def test_oversized_metadata_raises(self, repo):
        big = {k: "x" * 2000 for k in list(METADATA_ALLOWLIST)[:5]}
        with pytest.raises(ValueError, match="8KB"):
            repo._validate_metadata(big)


class TestCreateTradeValidation:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_symbol_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid symbol"):
            await repo.create_trade(conn, account_id="a", symbol="bad symbol!", side="Buy", qty=1.0)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_side_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid side"):
            await repo.create_trade(conn, account_id="a", symbol="BTCUSDT", side="Long", qty=1.0)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_metadata_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid metadata"):
            await repo.create_trade(
                conn, account_id="a", symbol="BTCUSDT", side="Buy", qty=1.0,
                metadata={"not_allowed": "val"},
            )


class TestListTradesValidation:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_sort_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid sort column"):
            await repo.list_trades(conn, account_id="a", sort="bad_col")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_symbol_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid symbol"):
            await repo.list_trades(conn, account_id="a", symbol="bad symbol!")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_status_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid status"):
            await repo.list_trades(conn, account_id="a", status="bogus")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_side_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid side"):
            await repo.list_trades(conn, account_id="a", side="Long")


class TestGetOpenTradesBySymbolSide:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_symbol_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid symbol"):
            await repo.get_open_trades_by_symbol_side(
                conn, account_id="a", symbol="bad!", side="Buy",
            )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_side_raises(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid side"):
            await repo.get_open_trades_by_symbol_side(
                conn, account_id="a", symbol="BTCUSDT", side="Long",
            )


class TestConstants:
    def test_valid_statuses_complete(self):
        assert "pending" in VALID_STATUSES
        assert "open" in VALID_STATUSES
        assert "closed" in VALID_STATUSES
        assert "failed" in VALID_STATUSES

    def test_valid_transitions_cover_non_terminal(self):
        from backend.services.trade_repository import TERMINAL_STATUSES
        for status in VALID_STATUSES - TERMINAL_STATUSES:
            assert status in VALID_TRANSITIONS

    def test_terminal_not_in_transitions(self):
        from backend.services.trade_repository import TERMINAL_STATUSES
        for status in TERMINAL_STATUSES:
            assert status not in VALID_TRANSITIONS

    def test_valid_sides(self):
        assert VALID_SIDES == {"Buy", "Sell"}

    def test_sort_columns(self):
        assert "created_at" in SORT_COLUMNS
        assert "realized_pnl" in SORT_COLUMNS


class TestExceptions:
    def test_trade_not_found(self):
        e = TradeNotFound("gone")
        assert str(e) == "gone"

    def test_invalid_status_transition(self):
        e = InvalidStatusTransition("bad")
        assert str(e) == "bad"

    def test_concurrent_modification(self):
        e = ConcurrentModification("conflict")
        assert str(e) == "conflict"


class TestCreateChildTradeValidation:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_close_reason(self, repo):
        conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid close_reason"):
            await repo.create_child_trade(
                conn, parent_trade={"id": uuid.uuid4(), "account_id": "a", "symbol": "BTCUSDT",
                                     "side": "Buy", "order_type": "market", "leverage": 10,
                                     "margin_mode": "isolated", "position_idx": 0, "source": "manual"},
                closed_qty=1.0, exit_price=50000, realized_pnl=100,
                realized_pnl_pct=2.0, fees=0.5, net_pnl=99.5,
                close_reason="invalid_reason",
            )
