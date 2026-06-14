"""FIX-003: per-position hard-loss force-close (the ESPORTS dead-zone).

Root cause (Unni investigation): a position losing MORE than
max_single_decision_loss_pct was silently skipped before the LLM on every eval,
so the BIGGEST losers never got closed. ESPORTS bled from -3% to -19% of equity
across 46 eval cycles with zero action. The 3% cap's intent ("don't realize a huge
loss in one careless decision") is moot once the loss already exists and is growing.

Fix: a deterministic per-position hard-loss trigger inside _check_emergency_close
(which runs BEFORE the LLM, circuit breaker, and token budget). A position whose
unrealized loss exceeds max_position_loss_pct of equity is force-closed for capital
preservation — calm or not, breaker tripped or not. MR/locked/excluded are spared,
mirroring the equity-drop branch.
"""

from __future__ import annotations

import logging

import pytest

from backend.services.ai_manager_task import AIManagerTask


class _FakeRepo:
    def __init__(self, result=None):
        self._result = result if result is not None else set()
        self.calls = 0

    async def get_open_mr_symbols(self, account_id):
        self.calls += 1
        return set(self._result)


class _FakeService:
    def __init__(self, repo):
        self._repo = repo


def _hardloss_task(positions, *, equity=100.0, ref_equity=None,
                   max_position_loss_pct=8.0, mr_symbols=None, excluded=None, locked=None):
    """Task wired so ONLY the per-position hard-loss path can trigger.

    ref_equity defaults to equity (no equity-drop), and no market_data is provided
    (no velocity), so the equity-drop and velocity branches stay inert — isolating
    the new hard-loss trigger.
    """
    t = object.__new__(AIManagerTask)
    t._log = logging.getLogger("test.fix003")
    t._account_id = "acct1"
    t._killed = False
    t._emergency_in_progress = False
    t._emergency_cooldown_until = 0.0
    t._emergency_closed_symbols = {}
    t._mr_symbols = set(mr_symbols or set())
    t._mr_symbols_primed = True
    t._service = _FakeService(_FakeRepo(set()))
    t._ws_buffer = {
        "positions": positions,
        "equity": equity,
        "_emergency_ref_equity": equity if ref_equity is None else ref_equity,
    }

    class _Cfg:
        emergency_close_enabled = True
        dry_run = False
        excluded_symbols = list(excluded or [])
        locked_positions = list(locked or [])
        emergency_equity_drop_pct = 10.0
        emergency_pnl_velocity_pct = 5.0
        max_position_loss_pct = None  # set below so None-default can be tested too
    cfg = _Cfg()
    cfg.max_position_loss_pct = max_position_loss_pct
    t._config = cfg

    # No market data -> velocity branch inert.
    t._get_market_data = lambda: {}

    class _Evaluator:
        # velocity branch: no emergency signals (isolates the hard-loss path)
        def check_emergency_signals(self, pos, indicators, threshold):
            return False
    t._evaluator = _Evaluator()

    closed = {}

    async def _fake_batch_close(symbols, reason):
        closed["symbols"] = list(symbols)
        closed["reason"] = reason
        return True

    t._execute_emergency_batch_close = _fake_batch_close
    return t, closed


@pytest.mark.asyncio
async def test_hard_loss_force_closes_big_calm_loser():
    """A position losing > max_position_loss_pct of equity, with NO equity-drop and
    NO velocity, must be force-closed (the ESPORTS dead-zone)."""
    # equity 100, ref 100 (no drop). One position at -12% of equity (> 8% hard cap).
    positions = [{"symbol": "ESPORTSUSDT", "side": "Sell", "unrealisedPnl": "-12.0"}]
    t, closed = _hardloss_task(positions, equity=100.0, max_position_loss_pct=8.0)
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["ESPORTSUSDT"]
    assert "loss" in closed.get("reason", "")


@pytest.mark.asyncio
async def test_hard_loss_ignores_small_loser():
    """A position losing LESS than the hard cap must NOT be force-closed here (the
    LLM/standard path owns that decision)."""
    positions = [{"symbol": "BTCUSDT", "side": "Buy", "unrealisedPnl": "-2.0"}]  # -2% < 8%
    t, closed = _hardloss_task(positions, equity=100.0, max_position_loss_pct=8.0)
    fired = await t._check_emergency_close()
    assert fired is False
    assert "symbols" not in closed


@pytest.mark.asyncio
async def test_hard_loss_only_closes_over_cap_positions():
    """With several positions, only those over the hard cap are closed; smaller
    losers and winners are left for the normal path."""
    positions = [
        {"symbol": "BIGUSDT", "side": "Sell", "unrealisedPnl": "-15.0"},  # -15% -> close
        {"symbol": "SMALLUSDT", "side": "Buy", "unrealisedPnl": "-2.0"},  # -2% -> keep
        {"symbol": "WINUSDT", "side": "Buy", "unrealisedPnl": "5.0"},     # winner -> keep
    ]
    t, closed = _hardloss_task(positions, equity=100.0, max_position_loss_pct=8.0)
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["BIGUSDT"]


@pytest.mark.asyncio
async def test_hard_loss_spares_mr_and_locked():
    """MR and locked positions are spared even when over the hard cap (F2/operator own them)."""
    positions = [
        {"symbol": "MRUSDT", "side": "Sell", "unrealisedPnl": "-20.0"},    # MR -> spared
        {"symbol": "LOCKUSDT", "side": "Sell", "unrealisedPnl": "-20.0"},  # locked -> spared
        {"symbol": "FREEUSDT", "side": "Sell", "unrealisedPnl": "-20.0"},  # -> close
    ]
    t, closed = _hardloss_task(
        positions, equity=100.0, max_position_loss_pct=8.0,
        mr_symbols={"MRUSDT"}, locked=["LOCKUSDT"],
    )
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["FREEUSDT"]


@pytest.mark.asyncio
async def test_hard_loss_disabled_when_unset():
    """When max_position_loss_pct is None (disabled), the hard-loss path never fires."""
    positions = [{"symbol": "ESPORTSUSDT", "side": "Sell", "unrealisedPnl": "-50.0"}]
    t, closed = _hardloss_task(positions, equity=100.0, max_position_loss_pct=None)
    fired = await t._check_emergency_close()
    assert fired is False
    assert "symbols" not in closed
