"""FIX-004: post-emergency drawdown reference must not desensitize on an open loser.

Root cause (Unni investigation): after an emergency close, _emergency_ref_equity is
cleared and re-seeds from the next equity reading — the LOWERED post-close equity. A
position still open and bleeding is then measured against that lowered baseline, so
its ongoing drawdown no longer reads as a large drop and the equity-drop emergency
never re-triggers. (ESPORTS bled $84 -> $79 after the 02:58 close but the reference
had reset to ~$84, so the drop read as ~6% < 10%.)

Fix: when (re)seeding the reference, floor it by the still-open unrealized losses —
ref = equity + |open unrealized losses| — so an open loser keeps counting against the
high-water mark it is actually drawing down from. Complements FIX-003 (absolute
hard-loss backstop) by restoring RELATIVE drawdown protection in the 3-8% band.
"""

from __future__ import annotations

import logging

import pytest

from backend.services.ai_manager_task import AIManagerTask


class _FakeRepo:
    def __init__(self):
        self.calls = 0

    async def get_open_mr_symbols(self, account_id):
        self.calls += 1
        return set()


class _FakeService:
    def __init__(self, repo):
        self._repo = repo
        self._accounts_service = None  # force WS-buffer-only path (isolate ref logic)


def _pos(symbol, upnl, side="Sell"):
    return {"symbol": symbol, "side": side, "size": "1", "unrealisedPnl": str(upnl)}


def _task(positions, equity, ref_equity):
    t = object.__new__(AIManagerTask)
    t._log = logging.getLogger("test.fix004")
    t._account_id = "acct1"
    t._killed = False
    t._emergency_in_progress = False
    t._emergency_cooldown_until = 0.0
    t._emergency_closed_symbols = {}
    t._mr_symbols = set()
    t._mr_symbols_primed = True
    t._service = _FakeService(_FakeRepo())
    t._ws_buffer = {"positions": positions, "equity": equity}
    if ref_equity is not None:
        t._ws_buffer["_emergency_ref_equity"] = ref_equity

    class _Cfg:
        emergency_close_enabled = True
        dry_run = False
        excluded_symbols = []
        locked_positions = []
        emergency_equity_drop_pct = 10.0
        emergency_pnl_velocity_pct = 5.0
        max_position_loss_pct = None  # isolate the equity-drop / reference logic
    t._config = _Cfg()
    t._get_market_data = lambda: {}

    class _Evaluator:
        def check_emergency_signals(self, pos, indicators, threshold):
            return False
    t._evaluator = _Evaluator()

    closed = {}

    async def _fake_batch_close(symbols, reason):
        closed["symbols"] = sorted(symbols)
        closed["reason"] = reason
        return True
    t._execute_emergency_batch_close = _fake_batch_close

    async def _noop_persist(*a, **k):
        return None
    t._persist_ref_equity = _noop_persist
    return t, closed


@pytest.mark.asyncio
async def test_reference_reseed_floors_by_open_unrealized_loss():
    """No reference yet (post-close state): seeding must floor by the open loss so the
    reference reflects the high-water the open loser is drawing down from."""
    # equity 84, ESPORTS open at -14 -> reference should seed to ~98 (84 + 14), not 84.
    t, _ = _task([_pos("ESPORTSUSDT", -14.0)], equity=84.0, ref_equity=None)
    await t._check_emergency_close()
    seeded = t._ws_buffer.get("_emergency_ref_equity")
    assert seeded == pytest.approx(98.0, abs=0.01), f"got {seeded}"


@pytest.mark.asyncio
async def test_open_loser_retriggers_after_reference_reseed():
    """The desensitization bug: after the reference re-seeds at the lowered equity, an
    open loser that keeps bleeding must STILL re-trigger the equity-drop emergency."""
    # Tick 1: no reference; equity 84, ESPORTS -14 -> reference seeds to ~98 (floored).
    t, closed = _task([_pos("ESPORTSUSDT", -14.0)], equity=84.0, ref_equity=None)
    fired1 = await t._check_emergency_close()
    # First tick only seeds the reference (no trigger on the seeding tick).
    assert fired1 is False
    # Tick 2: ESPORTS bled further -> equity 79, upnl -19. Drop from ~98 = ~19% >= 10%.
    t._ws_buffer["positions"] = [_pos("ESPORTSUSDT", -19.0)]
    t._ws_buffer["equity"] = 79.0
    fired2 = await t._check_emergency_close()
    assert fired2 is True
    assert closed.get("symbols") == ["ESPORTSUSDT"]


@pytest.mark.asyncio
async def test_reference_floor_noop_when_no_open_losses():
    """With no open losses, seeding is unchanged (reference == current equity)."""
    t, _ = _task([_pos("WINUSDT", 5.0)], equity=105.0, ref_equity=None)
    await t._check_emergency_close()
    assert t._ws_buffer.get("_emergency_ref_equity") == pytest.approx(105.0, abs=0.01)


@pytest.mark.asyncio
async def test_reference_ratchets_up_unaffected():
    """The upward ratchet (high-water mark) still works: a higher equity raises the
    reference (the floor only affects the seeding-from-empty case)."""
    t, _ = _task([_pos("WINUSDT", 10.0)], equity=120.0, ref_equity=100.0)
    await t._check_emergency_close()
    assert t._ws_buffer.get("_emergency_ref_equity") == pytest.approx(120.0, abs=0.01)
