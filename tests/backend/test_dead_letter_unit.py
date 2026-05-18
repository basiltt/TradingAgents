"""Unit tests for the dead-letter queue module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.dead_letter import DeadLetterQueue


class FakeConn:
    def __init__(self, return_id="abc-123"):
        self._return_id = return_id
        self.executed = []

    async def fetchrow(self, sql, *args):
        self.executed.append(("fetchrow", sql, args))
        return {"id": self._return_id}

    async def fetch(self, sql, *args):
        self.executed.append(("fetch", sql, args))
        return []

    async def execute(self, sql, *args):
        self.executed.append(("execute", sql, args))
        return "UPDATE 1"


class FakeDB:
    def __init__(self):
        self._conn = FakeConn()

    class _CM:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *a):
            pass

    def pool_acquire(self):
        return self._CM(self._conn)


@pytest.mark.asyncio
async def test_record_failure():
    db = FakeDB()
    dlq = DeadLetterQueue(db)
    err = ValueError("something went wrong")

    result = await dlq.record_failure("analysis", {"ticker": "AAPL"}, err)
    assert result == "abc-123"
    assert len(db._conn.executed) == 1
    call = db._conn.executed[0]
    assert call[0] == "fetchrow"
    assert "INSERT INTO dead_letter" in call[1]
    assert call[2][0] == "analysis"
    assert "AAPL" in call[2][1]
    assert call[2][2] == "ValueError"


@pytest.mark.asyncio
async def test_record_failure_truncates_message():
    db = FakeDB()
    dlq = DeadLetterQueue(db)
    err = RuntimeError("x" * 5000)

    await dlq.record_failure("trade_open", {}, err)
    call = db._conn.executed[0]
    assert len(call[2][3]) == 2000


@pytest.mark.asyncio
async def test_get_pending():
    db = FakeDB()
    dlq = DeadLetterQueue(db)
    result = await dlq.get_pending("analysis")
    assert result == []
    assert "operation" in db._conn.executed[0][1]


@pytest.mark.asyncio
async def test_resolve():
    db = FakeDB()
    dlq = DeadLetterQueue(db)
    result = await dlq.resolve("some-id", "operator1")
    assert result is True


@pytest.mark.asyncio
async def test_record_failure_handles_db_error():
    db = MagicMock()
    db.pool_acquire.side_effect = RuntimeError("pool closed")
    dlq = DeadLetterQueue(db)

    result = await dlq.record_failure("snapshot", {}, ValueError("err"))
    assert result is None
