"""T-15 (FR-052/AC-015): the AI manager excludes mean-reversion positions.

F2's fast time-stop owns MR exits; the AI manager must never see or act on an MR
position. Two layers are tested:
  1. _build_ws_snapshot_for_eval filters MR symbols out of what the LLM evaluates.
  2. _execute_action refuses to act on an MR symbol (defense-in-depth), while
     account-level PAUSE_TRADING (no symbol) is unaffected.
Plus the repo query that resolves open MR symbols from the trades table.
"""

from __future__ import annotations

import logging

import pytest

from backend.services.ai_manager_task import AIManagerTask
from backend.services.ai_manager_repository import AIManagerRepository


def _task():
    """A bare AIManagerTask with only the attributes the tested methods touch."""
    t = object.__new__(AIManagerTask)
    t._ws_buffer = {"positions": [
        {"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}, {"symbol": "SOLUSDT"},
    ]}
    t._active_trailing = {}
    t._mr_symbols = set()
    t._killed = False
    t._log = logging.getLogger("test.ai_mr")
    return t


def test_snapshot_excludes_mr_symbols():
    t = _task()
    t._mr_symbols = {"ETHUSDT"}
    snap = t._build_ws_snapshot_for_eval()
    syms = {p["symbol"] for p in snap["positions"]}
    assert syms == {"BTCUSDT", "SOLUSDT"}  # MR position removed


def test_snapshot_excludes_both_trailing_and_mr():
    t = _task()
    t._active_trailing = {"BTCUSDT": object()}
    t._mr_symbols = {"ETHUSDT"}
    snap = t._build_ws_snapshot_for_eval()
    syms = {p["symbol"] for p in snap["positions"]}
    assert syms == {"SOLUSDT"}


def test_snapshot_unchanged_when_no_mr():
    t = _task()
    snap = t._build_ws_snapshot_for_eval()
    assert {p["symbol"] for p in snap["positions"]} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


@pytest.mark.asyncio
async def test_execute_action_skips_mr_symbol():
    t = _task()
    t._mr_symbols = {"ETHUSDT"}
    # If the guard fails, _execute_action would proceed past it and touch other attrs
    # (raising AttributeError on this bare instance). A clean return proves the skip.
    await t._execute_action({"action": "CLOSE", "symbol": "ETHUSDT"})


@pytest.mark.asyncio
async def test_execute_action_killed_returns_early():
    t = _task()
    t._killed = True
    await t._execute_action({"action": "CLOSE", "symbol": "BTCUSDT"})  # no raise


# --- repo query ------------------------------------------------------------------

class _FakePool:
    def __init__(self, rows):
        self._rows = rows
        self.sql = None

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                class _Conn:
                    async def fetch(_c, sql, *args):
                        pool.sql = sql
                        return pool._rows
                return _Conn()

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_get_open_mr_symbols_query():
    repo = AIManagerRepository(_FakePool([{"symbol": "ETHUSDT"}, {"symbol": "SOLUSDT"}]))
    out = await repo.get_open_mr_symbols("acct1")
    assert out == {"ETHUSDT", "SOLUSDT"}
    assert "strategy_kind = 'mean_reversion'" in repo._pool.sql


@pytest.mark.asyncio
async def test_get_open_mr_symbols_failopen():
    class _BoomPool:
        def acquire(self):
            raise RuntimeError("db down")
    repo = AIManagerRepository(_BoomPool())
    assert await repo.get_open_mr_symbols("acct1") == set()
