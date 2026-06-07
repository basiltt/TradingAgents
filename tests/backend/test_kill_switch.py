"""Tests for the kill-switch reader (Phase 1 TASK-1.6)."""

import pytest

from backend.services.kill_switch import read_kill_switches, is_killed


class _FakePool:
    def __init__(self, rows=None, raise_exc=False):
        self._rows = rows or []
        self._raise = raise_exc

    async def fetch(self, *args, **kwargs):
        if self._raise:
            raise RuntimeError("db down")
        return self._rows


class _FakeDB:
    def __init__(self, rows=None, raise_exc=False):
        self.pool = _FakePool(rows, raise_exc)


# ── is_killed semantics ──

def test_is_killed_master_disables_all():
    kill = {"__all__": True}
    assert is_killed(kill, "f1") is True
    assert is_killed(kill, "f2") is True
    assert is_killed(kill, "anything") is True


def test_is_killed_per_feature():
    kill = {"f2": True}
    assert is_killed(kill, "f2") is True
    assert is_killed(kill, "f1") is False


def test_is_killed_no_row_not_killed():
    assert is_killed({}, "f2") is False  # T-21: empty => not killed


# ── read_kill_switches ──

@pytest.mark.asyncio
async def test_read_maps_killed_column_verbatim():
    db = _FakeDB(rows=[{"feature_name": "f2", "killed": True},
                       {"feature_name": "f1", "killed": False}])
    kill = await read_kill_switches(db)
    assert kill == {"f2": True, "f1": False}
    assert is_killed(kill, "f2") is True
    assert is_killed(kill, "f1") is False


@pytest.mark.asyncio
async def test_read_failure_fails_closed():
    db = _FakeDB(raise_exc=True)
    kill = await read_kill_switches(db)
    assert kill == {"__all__": True}
    assert is_killed(kill, "f2") is True  # read-failure => everything killed


@pytest.mark.asyncio
async def test_read_empty_table_not_killed():
    db = _FakeDB(rows=[])
    kill = await read_kill_switches(db)
    assert kill == {}
    assert is_killed(kill, "f2") is False
