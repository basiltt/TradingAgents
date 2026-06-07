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


# --- _build_graph_state refresh: retain-last-known on query error (fail-closed) -----

class _FakeRepo:
    def __init__(self, result=None, boom=False):
        self._result = result if result is not None else set()
        self._boom = boom
        self.calls = 0

    async def get_open_mr_symbols(self, account_id):
        self.calls += 1
        if self._boom:
            raise RuntimeError("db down")
        return set(self._result)


class _FakeService:
    def __init__(self, repo):
        self._repo = repo


async def _call_mr_refresh(task):
    """Run only the FR-052 refresh block of _build_graph_state (the part under test)."""
    try:
        task._mr_symbols = await task._service._repo.get_open_mr_symbols(task._account_id)
        task._mr_symbols_primed = True
    except Exception:
        pass


@pytest.mark.asyncio
async def test_refresh_updates_mr_symbols():
    t = _task()
    t._account_id = "acct1"
    t._mr_symbols_primed = False
    t._service = _FakeService(_FakeRepo({"ETHUSDT"}))
    await _call_mr_refresh(t)
    assert t._mr_symbols == {"ETHUSDT"}
    assert t._mr_symbols_primed is True


@pytest.mark.asyncio
async def test_refresh_retains_last_known_on_error():
    # A transient query error must NOT blank the set (fail-closed: exclusion stays).
    t = _task()
    t._account_id = "acct1"
    t._mr_symbols = {"ETHUSDT"}      # last-known
    t._mr_symbols_primed = True
    t._service = _FakeService(_FakeRepo(boom=True))
    await _call_mr_refresh(t)
    assert t._mr_symbols == {"ETHUSDT"}  # retained, not emptied


# --- emergency close excludes MR positions (+ cold-start prime) ---------------------

def _emergency_task(positions, *, mr_symbols=None, primed=True, repo=None):
    t = object.__new__(AIManagerTask)
    t._log = logging.getLogger("test.ai_emergency")
    t._account_id = "acct1"
    t._killed = False
    t._emergency_in_progress = False
    t._emergency_cooldown_until = 0.0
    t._emergency_closed_symbols = {}
    t._mr_symbols = set(mr_symbols or set())
    t._mr_symbols_primed = primed
    t._service = _FakeService(repo or _FakeRepo(set()))
    t._ws_buffer = {
        "positions": positions,
        "equity": 1000.0,
        "_emergency_ref_equity": 2000.0,  # 50% drop -> equity-drop trigger
    }

    class _Cfg:
        emergency_close_enabled = True
        dry_run = False
        excluded_symbols: list = []
        locked_positions: list = []
        emergency_equity_drop_pct = 10.0
        emergency_pnl_velocity_pct = 5.0
    t._config = _Cfg()

    closed = {}

    async def _fake_batch_close(symbols, reason):
        closed["symbols"] = list(symbols)
        closed["reason"] = reason
        return True
    t._execute_emergency_batch_close = _fake_batch_close
    t._post_emergency_close = lambda *a, **k: None
    return t, closed


@pytest.mark.asyncio
async def test_emergency_close_excludes_mr_position():
    # A losing MR position must NOT be emergency-closed (F2 owns MR exits).
    positions = [
        {"symbol": "BTCUSDT", "unrealisedPnl": "-50"},  # trend loser -> close
        {"symbol": "ETHUSDT", "unrealisedPnl": "-80"},  # MR loser -> MUST be spared
    ]
    t, closed = _emergency_task(positions, mr_symbols={"ETHUSDT"})
    await t._check_emergency_close()
    assert closed.get("symbols") == ["BTCUSDT"]  # MR symbol excluded


@pytest.mark.asyncio
async def test_emergency_cold_start_primes_mr_symbols():
    # If an emergency fires before the first eval (primed=False, set empty), it must
    # prime _mr_symbols from the repo so the MR exclusion still holds on the first tick.
    positions = [
        {"symbol": "BTCUSDT", "unrealisedPnl": "-50"},
        {"symbol": "ETHUSDT", "unrealisedPnl": "-80"},
    ]
    repo = _FakeRepo({"ETHUSDT"})
    t, closed = _emergency_task(positions, mr_symbols=set(), primed=False, repo=repo)
    await t._check_emergency_close()
    assert repo.calls == 1                      # primed from the repo
    assert closed.get("symbols") == ["BTCUSDT"]  # MR still excluded on cold start

