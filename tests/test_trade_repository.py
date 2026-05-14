"""Tests for backend.services.trade_repository.TradeRepository."""

from __future__ import annotations

import json
import uuid
from base64 import b64encode
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.trade_repository import (
    VALID_TRANSITIONS,
    ConcurrentModification,
    InvalidStatusTransition,
    TradeNotFound,
    TradeRepository,
)


def _make_trade_row(**overrides) -> dict:
    defaults = {
        "id": uuid.uuid4(),
        "account_id": "acc-1",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "order_type": "market",
        "qty": 0.01,
        "leverage": 10,
        "margin_mode": "isolated",
        "position_idx": 0,
        "status": "pending",
        "version": 1,
        "order_id": None,
        "order_link_id": str(uuid.uuid4()),
        "entry_price": None,
        "avg_fill_price": None,
        "exit_price": None,
        "stop_loss_price": None,
        "take_profit_price": None,
        "mark_price_at_open": None,
        "capital_pct": None,
        "base_capital": None,
        "signal_direction": None,
        "trade_direction": None,
        "take_profit_pct": None,
        "stop_loss_pct": None,
        "realized_pnl": None,
        "realized_pnl_pct": None,
        "fees": None,
        "net_pnl": None,
        "close_reason": None,
        "source": "manual",
        "source_id": None,
        "parent_trade_id": None,
        "metadata": "{}",
        "created_at": datetime.now(timezone.utc),
        "opened_at": None,
        "closed_at": None,
    }
    defaults.update(overrides)
    return defaults


class _FakeRecord(dict):
    """Mimics asyncpg.Record — subscriptable and dict()-castable."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _rec(**kw) -> _FakeRecord:
    return _FakeRecord(_make_trade_row(**kw))


@pytest.fixture
def conn():
    c = AsyncMock()
    c.fetchrow = AsyncMock()
    c.fetch = AsyncMock(return_value=[])
    c.fetchval = AsyncMock(return_value=0)
    c.execute = AsyncMock()
    return c


@pytest.fixture
def repo():
    db = MagicMock()
    return TradeRepository(db)


class TestCreateTrade:
    @pytest.mark.asyncio
    async def test_create_trade_returns_pending_with_order_link_id(self, conn, repo):
        row = _rec(status="pending")
        conn.fetchrow.return_value = row
        result = await repo.create_trade(
            conn, account_id="acc-1", symbol="BTCUSDT", side="Buy", qty=0.01,
        )
        assert result["status"] == "pending"
        assert result["order_link_id"] is not None
        conn.fetchrow.assert_awaited_once()
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_trade_creates_placed_event(self, conn, repo):
        row = _rec(id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
        conn.fetchrow.return_value = row
        await repo.create_trade(
            conn, account_id="acc-1", symbol="BTCUSDT", side="Buy", qty=0.01,
        )
        args = conn.execute.call_args
        assert "placed" in args[0][0]
        assert "pending" in args[0][0]

    @pytest.mark.asyncio
    async def test_create_trade_cycle_source(self, conn, repo):
        row = _rec(source="cycle")
        conn.fetchrow.return_value = row
        await repo.create_trade(
            conn, account_id="acc-1", symbol="BTCUSDT", side="Buy",
            qty=0.01, source="cycle", source_id=42, actor="cycle_engine",
        )
        event_sql = conn.execute.call_args[0][0]
        event_actor = conn.execute.call_args[0][2]
        assert "trade_events" in event_sql
        assert event_actor == "cycle_engine"

    @pytest.mark.asyncio
    async def test_create_trade_invalid_metadata_key_rejected(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid metadata keys"):
            await repo.create_trade(
                conn, account_id="acc-1", symbol="BTCUSDT", side="Buy",
                qty=0.01, metadata={"hack_key": "bad"},
            )

    @pytest.mark.asyncio
    async def test_create_trade_metadata_size_limit(self, conn, repo):
        big_val = "x" * 9000
        with pytest.raises(ValueError, match="8KB"):
            await repo.create_trade(
                conn, account_id="acc-1", symbol="BTCUSDT", side="Buy",
                qty=0.01, metadata={"reason": big_val},
            )

    @pytest.mark.asyncio
    async def test_create_trade_invalid_symbol_rejected(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid symbol"):
            await repo.create_trade(
                conn, account_id="acc-1", symbol="'; DROP TABLE--", side="Buy", qty=0.01,
            )


class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_valid_transition(self, conn, repo):
        current = _rec(status="pending", version=1)
        updated = _rec(status="open", version=2)
        conn.fetchrow.side_effect = [current, updated]
        result = await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status="open",
        )
        assert result["status"] == "open"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("old_status,new_status", [
        ("pending", "failed"),
        ("pending", "cancelled"),
        ("pending", "partially_filled"),
        ("open", "closing"),
        ("open", "partially_closed"),
        ("partially_filled", "open"),
        ("partially_filled", "closing"),
        ("closing", "closed"),
        ("closing", "open"),
        ("closing", "partially_closed"),
        ("partially_closed", "closing"),
        ("partially_closed", "closed"),
    ])
    async def test_all_valid_transitions(self, conn, repo, old_status, new_status):
        current = _rec(status=old_status, version=1)
        updated = _rec(status=new_status, version=2)
        conn.fetchrow.side_effect = [current, updated]
        result = await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status=new_status,
        )
        assert result["status"] == new_status

    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
    async def test_transition_from_terminal_rejected(self, conn, repo, terminal_status):
        current = _rec(status=terminal_status, version=1)
        conn.fetchrow.return_value = current
        with pytest.raises(InvalidStatusTransition):
            await repo.update_trade_status(
                conn, trade_id=str(current["id"]), account_id="acc-1",
                expected_version=1, new_status="open",
            )

    @pytest.mark.asyncio
    async def test_update_status_no_event_type_skips_event_insert(self, conn, repo):
        current = _rec(status="pending", version=1)
        updated = _rec(status="open", version=2)
        conn.fetchrow.side_effect = [current, updated]
        await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status="open",
        )
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_status_invalid_transition_raises(self, conn, repo):
        current = _rec(status="closed", version=1)
        conn.fetchrow.return_value = current
        with pytest.raises(InvalidStatusTransition):
            await repo.update_trade_status(
                conn, trade_id=str(current["id"]), account_id="acc-1",
                expected_version=1, new_status="open",
            )

    @pytest.mark.asyncio
    async def test_update_status_optimistic_lock_conflict(self, conn, repo):
        current = _rec(status="pending", version=2)
        conn.fetchrow.side_effect = [current, None]
        with pytest.raises(ConcurrentModification):
            await repo.update_trade_status(
                conn, trade_id=str(current["id"]), account_id="acc-1",
                expected_version=1, new_status="open",
            )

    @pytest.mark.asyncio
    async def test_update_status_creates_event(self, conn, repo):
        current = _rec(status="pending", version=1)
        updated = _rec(status="open", version=2)
        conn.fetchrow.side_effect = [current, updated]
        await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status="open",
            event_type="filled",
        )
        event_call = conn.execute.call_args
        assert "trade_events" in event_call[0][0]

    @pytest.mark.asyncio
    async def test_update_status_trade_not_found_raises(self, conn, repo):
        conn.fetchrow.return_value = None
        with pytest.raises(TradeNotFound):
            await repo.update_trade_status(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                expected_version=1, new_status="open",
            )

    @pytest.mark.asyncio
    async def test_update_status_invalid_column_rejected(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid update columns"):
            await repo.update_trade_status(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                expected_version=1, new_status="open",
                updates={"status = 'failed'; --": "x"},
            )

    @pytest.mark.asyncio
    async def test_update_status_uses_for_update(self, conn, repo):
        current = _rec(status="pending", version=1)
        updated = _rec(status="open", version=2)
        conn.fetchrow.side_effect = [current, updated]
        await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status="open",
        )
        select_query = conn.fetchrow.call_args_list[0][0][0]
        assert "FOR UPDATE" in select_query


class TestCloseTrade:
    @pytest.mark.asyncio
    async def test_close_trade_sets_pnl_fields(self, conn, repo):
        current = _rec(status="closing", version=1)
        closed = _rec(status="closed", version=2, exit_price=50000.0,
                       realized_pnl=100.0, fees=1.5, net_pnl=98.5)
        conn.fetchrow.side_effect = [current, closed]
        result = await repo.close_trade(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, exit_price=50000.0, realized_pnl=100.0,
            realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
            close_reason="take_profit",
        )
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_close_trade_not_found_raises(self, conn, repo):
        conn.fetchrow.return_value = None
        with pytest.raises(TradeNotFound):
            await repo.close_trade(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                expected_version=1, exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="take_profit",
            )

    @pytest.mark.asyncio
    async def test_close_trade_invalid_transition_raises(self, conn, repo):
        current = _rec(status="pending", version=1)
        conn.fetchrow.return_value = current
        with pytest.raises(InvalidStatusTransition):
            await repo.close_trade(
                conn, trade_id=str(current["id"]), account_id="acc-1",
                expected_version=1, exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="take_profit",
            )

    @pytest.mark.asyncio
    async def test_close_trade_concurrent_modification(self, conn, repo):
        current = _rec(status="closing", version=1)
        conn.fetchrow.side_effect = [current, None]
        with pytest.raises(ConcurrentModification):
            await repo.close_trade(
                conn, trade_id=str(current["id"]), account_id="acc-1",
                expected_version=1, exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="take_profit",
            )

    @pytest.mark.asyncio
    async def test_close_trade_creates_closed_event(self, conn, repo):
        current = _rec(status="closing", version=1)
        closed = _rec(status="closed", version=2)
        conn.fetchrow.side_effect = [current, closed]
        await repo.close_trade(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, exit_price=50000.0, realized_pnl=100.0,
            realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
            close_reason="take_profit",
        )
        event_sql = conn.execute.call_args[0][0]
        assert "'closed'" in event_sql
        payload_json = conn.execute.call_args[0][3]
        assert "take_profit" in payload_json
    @pytest.mark.asyncio
    async def test_reconcile_close_atomic(self, conn, repo):
        row = _rec(status="open", version=1)
        closed = _rec(status="closed", version=2)
        conn.fetchrow.side_effect = [row, closed]
        result = await repo.reconcile_close(
            conn, trade_id=str(row["id"]), account_id="acc-1",
            exit_price=50000.0, realized_pnl=100.0,
            realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
            close_reason="stop_loss",
        )
        assert result["status"] == "closed"
        assert conn.execute.await_count == 1
        event_sql = conn.execute.call_args[0][0]
        assert "reconciled" in event_sql

    @pytest.mark.asyncio
    async def test_reconcile_close_already_closed_raises(self, conn, repo):
        conn.fetchrow.return_value = None
        with pytest.raises(ConcurrentModification):
            await repo.reconcile_close(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="stop_loss",
            )

    @pytest.mark.asyncio
    async def test_reconcile_close_version_mismatch_raises(self, conn, repo):
        row = _rec(status="open", version=1)
        conn.fetchrow.side_effect = [row, None]
        with pytest.raises(ConcurrentModification, match="during reconciliation"):
            await repo.reconcile_close(
                conn, trade_id=str(row["id"]), account_id="acc-1",
                exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="stop_loss",
            )

    @pytest.mark.asyncio
    async def test_reconcile_close_invalid_close_reason_raises(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid close_reason"):
            await repo.reconcile_close(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="hacked",
            )


class TestGetTrade:
    @pytest.mark.asyncio
    async def test_get_trade_idor_prevention(self, conn, repo):
        conn.fetchrow.return_value = None
        result = await repo.get_trade(
            conn, account_id="acc-OTHER", trade_id=str(uuid.uuid4()),
        )
        assert result is None
        query = conn.fetchrow.call_args[0][0]
        assert "account_id" in query

    @pytest.mark.asyncio
    async def test_get_trade_returns_trade_on_match(self, conn, repo):
        trade = _rec(status="open")
        conn.fetchrow.return_value = trade
        result = await repo.get_trade(
            conn, account_id="acc-1", trade_id=str(trade["id"]),
        )
        assert result is not None
        assert result["status"] == "open"


class TestGetTradeWithEvents:
    @pytest.mark.asyncio
    async def test_get_trade_with_events_returns_trade_and_events(self, conn, repo):
        trade = _rec(status="open")
        events = [_FakeRecord({"id": 1, "event_type": "placed", "trade_id": trade["id"]})]
        conn.fetchrow.return_value = trade
        conn.fetch.return_value = events
        result = await repo.get_trade_with_events(
            conn, account_id="acc-1", trade_id=str(trade["id"]),
        )
        assert result is not None
        assert "events" in result
        assert len(result["events"]) == 1

    @pytest.mark.asyncio
    async def test_get_trade_with_events_not_found(self, conn, repo):
        conn.fetchrow.return_value = None
        result = await repo.get_trade_with_events(
            conn, account_id="acc-1", trade_id=str(uuid.uuid4()),
        )
        assert result is None


class TestListTrades:
    @pytest.mark.asyncio
    async def test_list_trades_pagination(self, conn, repo):
        rows = [_rec() for _ in range(3)]
        conn.fetch.return_value = rows
        result = await repo.list_trades(
            conn, account_id="acc-1", limit=2,
        )
        assert result["has_more"] is True
        assert len(result["items"]) == 2
        assert result["cursor"] is not None

    @pytest.mark.asyncio
    async def test_list_trades_filters(self, conn, repo):
        conn.fetch.return_value = []
        await repo.list_trades(
            conn, account_id="acc-1", status="open", symbol="BTCUSDT",
        )
        query = conn.fetch.call_args[0][0]
        assert "status" in query
        assert "symbol" in query

    @pytest.mark.asyncio
    async def test_list_trades_sort_allowlist(self, conn, repo):
        conn.fetch.return_value = []
        await repo.list_trades(
            conn, account_id="acc-1", sort="created_at",
        )
        query = conn.fetch.call_args[0][0]
        assert "created_at" in query

    @pytest.mark.asyncio
    async def test_list_trades_invalid_sort_raises(self, conn, repo):
        with pytest.raises(ValueError, match="sort"):
            await repo.list_trades(
                conn, account_id="acc-1", sort="DROP TABLE",
            )

    @pytest.mark.asyncio
    async def test_list_trades_symbol_validation(self, conn, repo):
        with pytest.raises(ValueError, match="symbol"):
            await repo.list_trades(
                conn, account_id="acc-1", symbol="'; DROP TABLE--",
            )

    @pytest.mark.asyncio
    async def test_list_trades_null_cursor_value_only_matches_nulls(self, conn, repo):
        """When cursor points to a NULL sort value, only NULL rows should be returned."""
        tid = uuid.uuid4()
        cursor_raw = f"NULL|{tid}"
        cursor_b64 = b64encode(cursor_raw.encode()).decode()
        conn.fetch.return_value = []
        await repo.list_trades(
            conn, account_id="acc-1", cursor=cursor_b64, sort="closed_at",
        )
        query = conn.fetch.call_args[0][0]
        assert "IS NULL AND" in query
        assert "IS NOT NULL" not in query

    @pytest.mark.asyncio
    async def test_list_trades_cursor_size_limit(self, conn, repo):
        with pytest.raises(ValueError, match="(?i)cursor"):
            await repo.list_trades(
                conn, account_id="acc-1", cursor="x" * 600,
            )

    @pytest.mark.asyncio
    async def test_list_trades_invalid_status_raises(self, conn, repo):
        with pytest.raises(ValueError, match="status"):
            await repo.list_trades(
                conn, account_id="acc-1", status="hacked",
            )

    @pytest.mark.asyncio
    async def test_list_trades_invalid_side_raises(self, conn, repo):
        with pytest.raises(ValueError, match="side"):
            await repo.list_trades(
                conn, account_id="acc-1", side="Sideways",
            )

    @pytest.mark.asyncio
    async def test_list_trades_include_total(self, conn, repo):
        conn.fetch.return_value = []
        conn.fetchval.return_value = 42
        result = await repo.list_trades(
            conn, account_id="acc-1", include_total=True,
        )
        assert result["total"] == 42
        conn.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_trades_limit_capped_at_200(self, conn, repo):
        conn.fetch.return_value = []
        await repo.list_trades(conn, account_id="acc-1", limit=500)
        query_params = conn.fetch.call_args[0]
        assert query_params[-1] == 201  # limit+1 where limit was capped to 200

    @pytest.mark.asyncio
    async def test_list_trades_malformed_cursor_raises(self, conn, repo):
        with pytest.raises(ValueError, match="cursor"):
            await repo.list_trades(
                conn, account_id="acc-1", cursor="not-valid-base64!!",
            )

    @pytest.mark.asyncio
    async def test_list_trades_close_reason_filter(self, conn, repo):
        conn.fetch.return_value = []
        await repo.list_trades(
            conn, account_id="acc-1", close_reason="stop_loss",
        )
        query = conn.fetch.call_args[0][0]
        assert "close_reason" in query

    @pytest.mark.asyncio
    async def test_list_trades_invalid_close_reason_filter_raises(self, conn, repo):
        with pytest.raises(ValueError, match="close_reason"):
            await repo.list_trades(
                conn, account_id="acc-1", close_reason="hacked",
            )

    @pytest.mark.asyncio
    async def test_list_trades_date_range_filters(self, conn, repo):
        conn.fetch.return_value = []
        from datetime import datetime, timezone
        d = datetime(2024, 1, 1, tzinfo=timezone.utc)
        await repo.list_trades(
            conn, account_id="acc-1", from_date=d, to_date=d,
        )
        query = conn.fetch.call_args[0][0]
        assert "created_at >=" in query
        assert "created_at <=" in query

    @pytest.mark.asyncio
    async def test_list_trades_parent_trade_id_filter(self, conn, repo):
        conn.fetch.return_value = []
        pid = str(uuid.uuid4())
        await repo.list_trades(
            conn, account_id="acc-1", parent_trade_id=pid,
        )
        query = conn.fetch.call_args[0][0]
        assert "parent_trade_id" in query

    @pytest.mark.asyncio
    async def test_list_trades_cursor_with_numeric_sort(self, conn, repo):
        tid = uuid.uuid4()
        cursor_raw = f"100.5|{tid}"
        cursor_b64 = b64encode(cursor_raw.encode()).decode()
        conn.fetch.return_value = []
        await repo.list_trades(
            conn, account_id="acc-1", cursor=cursor_b64, sort="realized_pnl",
        )
        query = conn.fetch.call_args[0][0]
        assert "numeric" in query


class TestGetOpenTrades:
    @pytest.mark.asyncio
    async def test_get_open_trades(self, conn, repo):
        rows = [_rec(status="open"), _rec(status="partially_filled")]
        conn.fetch.return_value = rows
        result = await repo.get_open_trades(conn, account_id="acc-1")
        assert len(result) == 2


class TestGetTradeStats:
    @pytest.mark.asyncio
    async def test_get_trade_stats_with_trades(self, conn, repo):
        conn.fetchrow.return_value = _FakeRecord({
            "total_trades": 10,
            "win_rate": 0.6,
            "avg_pnl": 50.0,
            "total_pnl": 500.0,
            "avg_hold_time": 3600.0,
        })
        result = await repo.get_trade_stats(conn, account_id="acc-1")
        assert result["total_trades"] == 10
        assert result["win_rate"] == 0.6
        assert result["total_pnl"] == 500.0

    @pytest.mark.asyncio
    async def test_get_trade_stats_empty(self, conn, repo):
        conn.fetchrow.return_value = _FakeRecord({
            "total_trades": 0,
            "win_rate": 0,
            "avg_pnl": 0,
            "total_pnl": 0,
            "avg_hold_time": None,
        })
        result = await repo.get_trade_stats(conn, account_id="acc-1")
        assert result["total_trades"] == 0
        assert result["win_rate"] == 0
        assert result["avg_hold_time"] is None


class TestCreateChildTrade:
    @pytest.mark.asyncio
    async def test_create_child_trade(self, conn, repo):
        parent = _make_trade_row(id=uuid.uuid4(), status="open")
        child = _rec(parent_trade_id=parent["id"], status="closed")
        conn.fetchrow.return_value = child
        result = await repo.create_child_trade(
            conn, parent_trade=parent, closed_qty=0.005,
            exit_price=50000.0, realized_pnl=50.0,
            realized_pnl_pct=1.25, fees=0.75, net_pnl=49.25,
            close_reason="partial_close",
        )
        assert result["status"] == "closed"
        assert result["parent_trade_id"] == parent["id"]
        conn.execute.assert_awaited_once()
        event_payload = json.loads(conn.execute.call_args[0][2])
        assert "parent_trade_id" in event_payload

    @pytest.mark.asyncio
    async def test_create_child_trade_invalid_close_reason_raises(self, conn, repo):
        parent = _make_trade_row(status="open")
        with pytest.raises(ValueError, match="Invalid close_reason"):
            await repo.create_child_trade(
                conn, parent_trade=parent, closed_qty=0.005,
                exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="hacked",
            )


class TestGetPendingOrphans:
    @pytest.mark.asyncio
    async def test_get_pending_orphans(self, conn, repo):
        rows = [_rec(status="pending", order_id=None)]
        conn.fetch.return_value = rows
        result = await repo.get_pending_orphans(conn, max_age_minutes=5)
        assert len(result) == 1
        query = conn.fetch.call_args[0][0]
        assert "pending" in query
        assert "order_id IS NULL" in query


class TestGetOpenTradesBySymbolSide:
    @pytest.mark.asyncio
    async def test_get_open_trades_by_symbol_side(self, conn, repo):
        rows = [_rec(status="open", symbol="BTCUSDT", side="Buy")]
        conn.fetch.return_value = rows
        result = await repo.get_open_trades_by_symbol_side(
            conn, account_id="acc-1", symbol="BTCUSDT", side="Buy",
        )
        assert len(result) == 1
        query = conn.fetch.call_args[0][0]
        assert "symbol" in query
        assert "side" in query
        assert "account_id" in query

    @pytest.mark.asyncio
    async def test_get_open_trades_by_symbol_side_invalid_symbol(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid symbol"):
            await repo.get_open_trades_by_symbol_side(
                conn, account_id="acc-1", symbol="bad!sym", side="Buy",
            )

    @pytest.mark.asyncio
    async def test_get_open_trades_by_symbol_side_invalid_side(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid side"):
            await repo.get_open_trades_by_symbol_side(
                conn, account_id="acc-1", symbol="BTCUSDT", side="Sideways",
            )


class TestAdditionalEdgeCases:
    @pytest.mark.asyncio
    async def test_update_status_invalid_status_value_raises(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid status"):
            await repo.update_trade_status(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                expected_version=1, new_status="bogus",
            )

    @pytest.mark.asyncio
    async def test_update_status_with_valid_updates(self, conn, repo):
        current = _rec(status="pending", version=1)
        updated = _rec(status="open", version=2, entry_price=50000.0)
        conn.fetchrow.side_effect = [current, updated]
        result = await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status="open",
            updates={"entry_price": 50000.0},
        )
        assert result is not None
        update_query = conn.fetchrow.call_args_list[1][0][0]
        assert "entry_price" in update_query

    @pytest.mark.asyncio
    async def test_update_status_event_payload_serialized(self, conn, repo):
        current = _rec(status="pending", version=1)
        updated = _rec(status="open", version=2)
        conn.fetchrow.side_effect = [current, updated]
        await repo.update_trade_status(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, new_status="open",
            event_type="filled", event_payload={"fill_qty": 0.005},
        )
        event_payload_json = conn.execute.call_args[0][6]
        assert "fill_qty" in event_payload_json

    @pytest.mark.asyncio
    async def test_create_trade_invalid_side_rejected(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid side"):
            await repo.create_trade(
                conn, account_id="acc-1", symbol="BTCUSDT",
                side="Sideways", qty=0.01,
            )

    @pytest.mark.asyncio
    async def test_list_trades_with_valid_cursor(self, conn, repo):
        tid = uuid.uuid4()
        cursor_raw = f"2024-01-01T00:00:00|{tid}"
        cursor_b64 = b64encode(cursor_raw.encode()).decode()
        conn.fetch.return_value = []
        await repo.list_trades(
            conn, account_id="acc-1", cursor=cursor_b64,
        )
        query = conn.fetch.call_args[0][0]
        assert "created_at" in query

    @pytest.mark.asyncio
    async def test_close_trade_invalid_close_reason_raises(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid close_reason"):
            await repo.close_trade(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                expected_version=1, exit_price=50000.0, realized_pnl=100.0,
                realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
                close_reason="hacked_reason",
            )

    @pytest.mark.asyncio
    async def test_close_trade_with_close_rule_id(self, conn, repo):
        current = _rec(status="closing", version=1)
        closed = _rec(status="closed", version=2)
        conn.fetchrow.side_effect = [current, closed]
        rule_id = str(uuid.uuid4())
        result = await repo.close_trade(
            conn, trade_id=str(current["id"]), account_id="acc-1",
            expected_version=1, exit_price=50000.0, realized_pnl=100.0,
            realized_pnl_pct=2.5, fees=1.5, net_pnl=98.5,
            close_reason="close_rule", close_rule_id=rule_id,
        )
        assert result is not None
        update_query = conn.fetchrow.call_args_list[1][0][0]
        assert "close_rule_id" in update_query

    @pytest.mark.asyncio
    async def test_update_status_invalid_event_type_raises(self, conn, repo):
        with pytest.raises(ValueError, match="Invalid event_type"):
            await repo.update_trade_status(
                conn, trade_id=str(uuid.uuid4()), account_id="acc-1",
                expected_version=1, new_status="open",
                event_type="hacked_event",
            )
        conn.fetchrow.assert_not_awaited()
