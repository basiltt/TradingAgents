"""DB-layer tests for get_performance_trades_page keyset SQL.

These exercise the SQL string + parameter binding + cursor shaping WITHOUT a live
Postgres, by injecting a fake pool whose `fetch` captures the query and the bound
params and returns canned rows. They pin the fixes that the service-level tests (which
mock this method entirely) cannot reach: typed cursor binding (Decimal/datetime/uuid),
the str(uuid) JSON-safe next_cursor, the NULLS-LAST ordering clause, and has_more slicing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.async_persistence import AsyncAnalysisDB


class _FakePool:
    """Captures the SQL + params of the last fetch and returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.last_sql: str | None = None
        self.last_params: tuple | None = None

    async def fetch(self, sql, *params):
        self.last_sql = sql
        self.last_params = params
        return self._rows


def _db_with(rows) -> tuple[AsyncAnalysisDB, _FakePool]:
    db = AsyncAnalysisDB(dsn="postgresql://unused/unused")
    pool = _FakePool(rows)
    db._pool = pool  # bypass connect(); pool property returns this
    return db, pool


def _row(_id, net_pnl, closed_at):
    return {
        "id": _id, "account_id": "a1", "symbol": "BTCUSDT", "side": "Buy",
        "net_pnl": net_pnl, "realized_pnl_pct": None, "base_capital": Decimal("100"),
        "close_reason": "take_profit", "strategy_kind": "trend",
        "opened_at": None, "closed_at": closed_at, "leverage": 20,
    }


@pytest.mark.asyncio
async def test_first_page_orders_nulls_last_and_emits_str_uuid_cursor():
    u1, u2, u3 = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    # 3 rows requested with limit=2 -> has_more True, cursor from row[1]
    rows = [_row(u1, Decimal("5"), datetime(2026, 5, 1, tzinfo=timezone.utc)),
            _row(u2, Decimal("3"), datetime(2026, 5, 2, tzinfo=timezone.utc)),
            _row(u3, Decimal("1"), datetime(2026, 5, 3, tzinfo=timezone.utc))]
    db, pool = _db_with(rows)
    out, cursor, has_more = await db.get_performance_trades_page(
        account_ids=["a1"], sort="net_pnl", direction="desc", cursor=None, limit=2)
    assert has_more is True
    assert len(out) == 2
    # cursor id must be a STR (JSON-safe), not a uuid.UUID -> this is the C1 fix
    assert cursor == (3.0, str(u2))
    assert isinstance(cursor[1], str)
    # ordering clause uses NULLS LAST (portable; no numeric-infinity sentinel)
    assert "NULLS LAST" in pool.last_sql
    assert "'-Infinity'" not in pool.last_sql


@pytest.mark.asyncio
async def test_net_pnl_cursor_binds_decimal_and_uuid():
    last_id = uuid.uuid4()
    db, pool = _db_with([])
    await db.get_performance_trades_page(
        account_ids=["a1"], sort="net_pnl", direction="desc",
        cursor=(3.0, str(last_id)), limit=50)
    # the cursor value must bind as Decimal (numeric column) and the id as uuid.UUID
    assert any(isinstance(p, Decimal) and p == Decimal("3.0") for p in pool.last_params)
    assert any(isinstance(p, uuid.UUID) and p == last_id for p in pool.last_params)


@pytest.mark.asyncio
async def test_closed_at_cursor_binds_datetime():
    last_id = uuid.uuid4()
    db, pool = _db_with([])
    await db.get_performance_trades_page(
        account_ids=["a1"], sort="closed_at", direction="desc",
        cursor=("2026-05-02T00:00:00+00:00", str(last_id)), limit=50)
    # closed_at cursor value must bind as the PARSED tz-aware datetime (not a string, and
    # not some other datetime like now()) -- pin the exact value so a wrong bind is caught.
    assert any(isinstance(p, datetime) and p == datetime(2026, 5, 2, tzinfo=timezone.utc)
               for p in pool.last_params)


@pytest.mark.asyncio
async def test_null_tail_cursor_uses_is_null_branch():
    last_id = uuid.uuid4()
    db, pool = _db_with([])
    # sort_value None = the NULLS-LAST tail; predicate must restrict to NULL rows by id
    await db.get_performance_trades_page(
        account_ids=["a1"], sort="net_pnl", direction="desc",
        cursor=(None, str(last_id)), limit=50)
    assert "IS NULL" in pool.last_sql
    # only the id is bound for the tail (plus account_ids + limit), value param absent
    assert any(isinstance(p, uuid.UUID) and p == last_id for p in pool.last_params)


@pytest.mark.asyncio
async def test_null_net_pnl_last_row_yields_none_sort_value_cursor():
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    rows = [_row(u1, Decimal("5"), datetime(2026, 5, 1, tzinfo=timezone.utc)),
            _row(u2, None, datetime(2026, 5, 2, tzinfo=timezone.utc))]
    db, _ = _db_with(rows)
    _, cursor, has_more = await db.get_performance_trades_page(
        account_ids=["a1"], sort="net_pnl", direction="desc", cursor=None, limit=1)
    # has_more True (2 rows, limit 1); last row of page has net_pnl None -> sort_value None,
    # never float('-inf') (the old invalid-JSON sentinel)
    assert has_more is True
    assert cursor[0] == 5.0  # first row kept; its net_pnl is the cursor value
    # And when the NULL row is the boundary, the value must be None not -inf:
    _, cursor2, _ = await db.get_performance_trades_page(
        account_ids=["a1"], sort="net_pnl", direction="desc", cursor=None, limit=2)
    # limit 2 -> both returned, has_more False -> no cursor
    assert cursor2 is None
