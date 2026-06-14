"""FIX-002: emergency equity-drop close must not miss a still-open loser.

Root cause (Unni investigation): _check_emergency_close enumerated losers from the
eventually-consistent WS position buffer. At 02:58:05 that buffer listed TSTBSC and
FOLKS (which had just closed on their own stop rules ms earlier) but NOT the
still-open ESPORTS, so the "close ALL losers" equity-drop branch closed two
already-gone positions and left the real loser open to ride to its stop (-$19).

Fix: on a CONFIRMED equity-drop emergency, enumerate losers from the AUTHORITATIVE
exchange snapshot (accounts_service.get_positions) UNION the WS-buffer losers — so a
frame the WS buffer dropped is still caught. On fetch failure, fall back to the WS
buffer alone (never close fewer than before). MR/locked/excluded still spared.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

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
    def __init__(self, repo, accounts_service=None):
        self._repo = repo
        self._accounts_service = accounts_service


def _equity_drop_task(ws_positions, exch_positions, *, equity=87.0, ref_equity=100.0,
                      mr_symbols=None, excluded=None, locked=None, exch_raises=False):
    """Task wired for an equity-drop emergency.

    ws_positions: what the (possibly stale) WS buffer holds.
    exch_positions: what the authoritative exchange snapshot returns.
    ref_equity 100 vs equity 87 -> 13% drop -> equity-drop emergency fires.
    """
    t = object.__new__(AIManagerTask)
    t._log = logging.getLogger("test.fix002")
    t._account_id = "acct1"
    t._killed = False
    t._emergency_in_progress = False
    t._emergency_cooldown_until = 0.0
    t._emergency_closed_symbols = {}
    t._mr_symbols = set(mr_symbols or set())
    t._mr_symbols_primed = True

    accounts_service = AsyncMock()
    if exch_raises:
        accounts_service.get_positions = AsyncMock(side_effect=RuntimeError("exchange down"))
    else:
        accounts_service.get_positions = AsyncMock(return_value=exch_positions)
    t._service = _FakeService(_FakeRepo(set()), accounts_service=accounts_service)

    t._ws_buffer = {
        "positions": ws_positions,
        "equity": equity,
        "_emergency_ref_equity": ref_equity,
    }

    class _Cfg:
        emergency_close_enabled = True
        dry_run = False
        excluded_symbols = list(excluded or [])
        locked_positions = list(locked or [])
        emergency_equity_drop_pct = 10.0
        emergency_pnl_velocity_pct = 5.0
        max_position_loss_pct = None  # isolate the equity-drop branch
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
    return t, closed, accounts_service


def _pos(symbol, upnl, side="Sell"):
    return {"symbol": symbol, "side": side, "size": "1", "unrealisedPnl": str(upnl)}


@pytest.mark.asyncio
async def test_equity_drop_closes_loser_missing_from_ws_buffer():
    """The WS buffer is missing the still-open ESPORTS loser (it lists two already-
    closed positions); the exchange snapshot has ESPORTS. The emergency must close
    ESPORTS (the real loser), sourced from the exchange union."""
    ws = [_pos("TSTBSCUSDT", -0.1), _pos("FOLKSUSDT", -0.2)]  # stale: about to vanish
    exch = [_pos("ESPORTSUSDT", -15.0)]                        # authoritative: the real loser
    t, closed, accounts = _equity_drop_task(ws, exch)
    fired = await t._check_emergency_close()
    assert fired is True
    accounts.get_positions.assert_awaited_once()
    # ESPORTS (exchange) must be included even though it was absent from the WS buffer.
    assert "ESPORTSUSDT" in closed.get("symbols", [])


@pytest.mark.asyncio
async def test_equity_drop_unions_ws_and_exchange():
    """Union semantics: a loser only in the WS buffer AND a loser only on the exchange
    are BOTH closed — we never close fewer than the WS buffer alone would."""
    ws = [_pos("WSONLYUSDT", -3.0)]      # present only in WS buffer
    exch = [_pos("EXCHONLYUSDT", -4.0)]  # present only on exchange
    t, closed, _ = _equity_drop_task(ws, exch)
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["EXCHONLYUSDT", "WSONLYUSDT"]


@pytest.mark.asyncio
async def test_equity_drop_falls_back_to_ws_on_exchange_error():
    """If the exchange fetch fails, fall back to the WS buffer losers — never close
    fewer than before, never crash the emergency."""
    ws = [_pos("AUSDT", -3.0), _pos("BUSDT", -2.0)]
    t, closed, accounts = _equity_drop_task(ws, [], exch_raises=True)
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["AUSDT", "BUSDT"]  # WS-buffer fallback


@pytest.mark.asyncio
async def test_equity_drop_union_spares_mr_and_locked():
    """MR/locked symbols are spared even when over the loss line in either source."""
    ws = [_pos("FREEUSDT", -5.0)]
    exch = [_pos("MRUSDT", -9.0), _pos("LOCKUSDT", -9.0), _pos("FREEUSDT", -5.0)]
    t, closed, _ = _equity_drop_task(
        ws, exch, mr_symbols={"MRUSDT"}, locked=["LOCKUSDT"],
    )
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["FREEUSDT"]


@pytest.mark.asyncio
async def test_equity_drop_only_closes_losers_not_winners():
    """Winners in the exchange snapshot are not closed — only negative-UPnL losers."""
    ws = [_pos("LOSERUSDT", -5.0)]
    exch = [_pos("LOSERUSDT", -5.0), _pos("WINNERUSDT", 8.0)]
    t, closed, _ = _equity_drop_task(ws, exch)
    fired = await t._check_emergency_close()
    assert fired is True
    assert closed.get("symbols") == ["LOSERUSDT"]


# --- audit gap: emergency batch close must persist execution_result -------------------

@pytest.mark.asyncio
async def test_emergency_batch_close_persists_execution_result():
    """FIX-002 audit gap: _execute_emergency_batch_close must record the close OUTCOME
    via update_decision_outcome (previously NULL on the emergency path, so the forensic
    record showed an emergency 'fired' with no evidence of what it closed)."""
    t = object.__new__(AIManagerTask)
    t._log = logging.getLogger("test.fix002.audit")
    t._account_id = "acct1"
    t._ws_buffer = {"positions": [_pos("ESPORTSUSDT", -15.0)]}

    class _Cfg:
        strategy_version = "default"
    t._config = _Cfg()

    close_positions_service = AsyncMock()
    close_positions_service.close_all_for_rule = AsyncMock(
        return_value={"closed": 1, "realized_pnl": -15.0, "skipped": False}
    )

    repo = AsyncMock()
    repo.insert_decision = AsyncMock(return_value=(42, "2026-06-14T02:58:05Z"))
    repo.update_decision_outcome = AsyncMock()

    service = AsyncMock()
    service._close_positions_service = close_positions_service
    service._repo = repo
    service._hmac_key = "k"
    service.emit_event = AsyncMock()
    t._service = service

    async def _noop(*a, **k):
        return None
    t._enforce_daily_limits = _noop
    t._log_async = lambda *a, **k: None

    ok = await t._execute_emergency_batch_close(["ESPORTSUSDT"], "equity_drop_15.0pct")
    assert ok is True
    repo.insert_decision.assert_awaited_once()
    # The outcome MUST be persisted (the whole point of the audit-gap fix).
    repo.update_decision_outcome.assert_awaited_once()
    args, kwargs = repo.update_decision_outcome.await_args
    outcome = args[2] if len(args) > 2 else kwargs.get("outcome")
    assert outcome["closed"] == 1
    assert outcome["symbols"] == ["ESPORTSUSDT"]
    assert outcome["realized_pnl"] == -15.0
