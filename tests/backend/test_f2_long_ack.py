"""Tests for f2_long_ack server-authoritative gate (Phase 4 TASK-4.5)."""

import pytest

from backend.services.f2_long_ack import is_long_acknowledged


class _Pool:
    def __init__(self, row=None, raise_exc=False):
        self._row = row
        self._raise = raise_exc

    async def fetchrow(self, *a):
        if self._raise:
            raise RuntimeError("db down")
        return self._row


class _DB:
    def __init__(self, row=None, raise_exc=False):
        self.pool = _Pool(row, raise_exc)


class _Accounts:
    def __init__(self, db):
        self._db = db


def _cfg(lev=10, cap=2.0, mx=2):
    return {"mr_leverage": lev, "mr_capital_pct": cap, "mr_max_trades": mx}


@pytest.mark.asyncio
async def test_no_row_not_acknowledged():
    acc = _Accounts(_DB(row=None))
    assert await is_long_acknowledged(acc, "a", _cfg()) is False


@pytest.mark.asyncio
async def test_fresh_ack_covers_current_exposure():
    acc = _Accounts(_DB(row={"acked_leverage": 10, "acked_capital_pct": 2.0, "acked_max_trades": 2}))
    assert await is_long_acknowledged(acc, "a", _cfg(10, 2.0, 2)) is True


@pytest.mark.asyncio
async def test_ack_stale_when_leverage_escalates():
    acc = _Accounts(_DB(row={"acked_leverage": 5, "acked_capital_pct": 2.0, "acked_max_trades": 2}))
    assert await is_long_acknowledged(acc, "a", _cfg(lev=20)) is False


@pytest.mark.asyncio
async def test_ack_stale_when_capital_escalates():
    acc = _Accounts(_DB(row={"acked_leverage": 10, "acked_capital_pct": 2.0, "acked_max_trades": 2}))
    assert await is_long_acknowledged(acc, "a", _cfg(cap=5.0)) is False


@pytest.mark.asyncio
async def test_ack_stale_when_max_trades_escalates():
    acc = _Accounts(_DB(row={"acked_leverage": 10, "acked_capital_pct": 2.0, "acked_max_trades": 2}))
    assert await is_long_acknowledged(acc, "a", _cfg(mx=5)) is False


@pytest.mark.asyncio
async def test_lower_then_raise_back_is_covered():
    # acked at high water mark 20; current 10 <= 20 => covered
    acc = _Accounts(_DB(row={"acked_leverage": 20, "acked_capital_pct": 10.0, "acked_max_trades": 5}))
    assert await is_long_acknowledged(acc, "a", _cfg(10, 2.0, 2)) is True


@pytest.mark.asyncio
async def test_read_failure_fails_closed():
    acc = _Accounts(_DB(raise_exc=True))
    assert await is_long_acknowledged(acc, "a", _cfg()) is False


@pytest.mark.asyncio
async def test_no_db_fails_closed():
    class _NoDB:
        _db = None
    assert await is_long_acknowledged(_NoDB(), "a", _cfg()) is False
