"""Orchestrator (run_post_scan_tail) tests — TASK-2.2.

Asserts the extracted orchestrator:
  * runs the 5 tail stages in order (execute_batch -> fill -> recheck -> cleanup ->
    summaries) and returns merged executions + summaries
  * invokes the injected persist_cb once per stage that produced executions, in order
  * emits stage-level progress (active/done) ONLY from the orchestrator (EC-1) with a
    single global pct (EC-2), and a terminal "complete" event last
  * is fail-open on a raising progress sink (execution unaffected)
  * is fail-open on a raising persist_cb (tail still completes, other stages persist)
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services import post_scan_concurrency as psc
from backend.services import post_scan_flags
from tests.backend.post_scan_harness import (
    RecordingAccountsService,
    RecordingCloseService,
    build_executor,
)


@pytest.fixture(autouse=True)
def _reset_state():
    psc.reset_for_tests()
    post_scan_flags.reset_for_tests()
    yield
    psc.reset_for_tests()
    post_scan_flags.reset_for_tests()


class RecordingProgress:
    """Captures emit() calls for assertion (mirrors ScanProgressManager.emit sig)."""

    def __init__(self):
        self.events = []

    def emit(self, scan_id, stage, label="", **fields):
        self.events.append({"scan_id": scan_id, "stage": stage, "label": label, **fields})
        return {}


def _cfg(account_id, **overrides):
    base = {
        "account_id": account_id, "execution_mode": "batch", "max_trades": 5,
        "min_score": 0, "signal_sides": "both", "leverage": 10,
        "take_profit_pct": 150, "stop_loss_pct": 100, "capital_pct": 10,
        "direction": "straight", "confidence_filter": "any",
    }
    base.update(overrides)
    return base


def _results(*tickers):
    return [
        {"id": f"r{i}", "ticker": t, "status": "completed", "direction": "sell",
         "score": -(10 - i), "confidence": "high"}
        for i, t in enumerate(tickers)
    ]


@pytest.mark.asyncio
async def test_orchestrator_runs_all_stages_and_returns_results():
    configs = [_cfg("accA"), _cfg("accB")]
    results = _results("BTC", "ETH")
    ex, accounts, close = build_executor(configs, scan_id="scan-1")

    out = await ex.run_post_scan_tail(results)

    # All placements happened (2 accounts x 2 symbols).
    assert len(accounts.placement_log) == 4
    assert out["summaries"]  # per-account summaries returned
    by_acct = {s["account_id"]: s["trades_executed"] for s in out["summaries"]}
    assert by_acct == {"accA": 2, "accB": 2}


@pytest.mark.asyncio
async def test_orchestrator_invokes_persist_cb_in_order():
    configs = [_cfg("accA")]
    results = _results("BTC", "ETH")
    ex, accounts, close = build_executor(configs, scan_id="scan-1")

    persisted_stages = []

    async def persist_cb(stage, executions):
        persisted_stages.append(stage)

    await ex.run_post_scan_tail(results, persist_cb=persist_cb)
    # batch produced executions; fill/recheck may be empty but stage order must hold
    # for the stages that did persist.
    assert persisted_stages[0] == "execute_batch"
    # No stage appears out of the canonical order.
    canonical = ["execute_batch", "fill", "post_scan_recheck"]
    seen_idx = [canonical.index(s) for s in persisted_stages if s in canonical]
    assert seen_idx == sorted(seen_idx)


@pytest.mark.asyncio
async def test_orchestrator_emits_stage_progress_and_terminal():
    configs = [_cfg("accA")]
    results = _results("BTC")
    prog = RecordingProgress()
    ex, accounts, close = build_executor(configs, progress=prog, scan_id="scan-1")

    await ex.run_post_scan_tail(results)

    stages = [(e["stage"], e.get("status")) for e in prog.events]
    # The terminal event is the last and is stage=complete/status=done.
    assert stages[-1] == ("complete", "done")
    # Every emitted event belongs to scan-1.
    assert all(e["scan_id"] == "scan-1" for e in prog.events)
    # At least the execute_batch stage emitted an active then a done.
    eb = [e for e in prog.events if e["stage"] == "execute_batch"]
    assert any(e.get("status") == "active" for e in eb)
    assert any(e.get("status") == "done" for e in eb)


@pytest.mark.asyncio
async def test_orchestrator_pct_is_monotonic_global():
    configs = [_cfg("accA"), _cfg("accB")]
    results = _results("BTC", "ETH")
    prog = RecordingProgress()
    ex, _accounts, _close = build_executor(configs, progress=prog, scan_id="scan-1")

    await ex.run_post_scan_tail(results)
    pcts = [e["pct"] for e in prog.events if e.get("pct") is not None]
    assert pcts == sorted(pcts), f"pct not monotonic: {pcts}"
    assert pcts[-1] == 100


@pytest.mark.asyncio
async def test_orchestrator_fail_open_on_raising_progress():
    class Boom:
        def emit(self, *a, **k):
            raise RuntimeError("progress sink down")

    configs = [_cfg("accA")]
    results = _results("BTC", "ETH")
    ex, accounts, _close = build_executor(configs, progress=Boom(), scan_id="scan-1")
    # Must complete despite the sink raising on every emit.
    out = await ex.run_post_scan_tail(results)
    assert len(accounts.placement_log) == 2
    assert out["summaries"]


@pytest.mark.asyncio
async def test_orchestrator_fail_open_on_raising_persist():
    configs = [_cfg("accA")]
    results = _results("BTC", "ETH")
    ex, accounts, _close = build_executor(configs, scan_id="scan-1")

    async def bad_persist(stage, executions):
        raise RuntimeError("db down")

    out = await ex.run_post_scan_tail(results, persist_cb=bad_persist)
    # Tail still completed and placed orders despite persist raising.
    assert len(accounts.placement_log) == 2
    assert out["summaries"]


@pytest.mark.asyncio
async def test_orchestrator_no_progress_no_scan_id_is_silent():
    # Backtest/no-services mode: neither progress nor scan_id => no emit, runs green.
    configs = [_cfg("accA")]
    results = _results("BTC")
    ex, accounts, _close = build_executor(configs)  # no progress, no scan_id
    out = await ex.run_post_scan_tail(results)
    assert len(accounts.placement_log) == 1
    assert out["summaries"]


# --------------------------------------------------------------------------- #
# Emit-contract (EC-1 / EC-2 / EC-3) assertions
# --------------------------------------------------------------------------- #

TERMINAL_STAGES = ("complete", "failed", "cancelled")


@pytest.mark.asyncio
async def test_per_account_emits_never_carry_terminal_stage_status():
    # EC-1: a per-account / per-symbol emit (stage = "batch"/"immediate") must never
    # carry status done/failed/cancelled ON A TERMINAL STAGE — only the orchestrator's
    # own complete/failed/cancelled events may. Per-account rows use the mode as stage.
    configs = [_cfg("accA"), _cfg("accB")]
    results = _results("BTC", "ETH")
    prog = RecordingProgress()
    ex, _accounts, _close = build_executor(configs, progress=prog, scan_id="scan-1")
    await ex.run_post_scan_tail(results)

    for e in prog.events:
        if e["stage"] in TERMINAL_STAGES:
            # Only the single terminal "complete" event is allowed here.
            assert e["stage"] == "complete" and e.get("status") == "done"
        else:
            # A non-terminal stage event may be active/done/placed/failed but its
            # stage is NEVER one of the terminal stage keys.
            assert e["stage"] not in TERMINAL_STAGES


@pytest.mark.asyncio
async def test_per_symbol_rows_carry_acct_ordinal_and_symbol():
    # EC-1/EC-3: each placed-order row carries a stable acct_ordinal + symbol.
    configs = [_cfg("accA"), _cfg("accB")]
    results = _results("BTC", "ETH")
    prog = RecordingProgress()
    ex, _accounts, _close = build_executor(configs, progress=prog, scan_id="scan-1")
    await ex.run_post_scan_tail(results)

    order_rows = [e for e in prog.events if e.get("symbol")]
    assert order_rows, "expected per-symbol order rows"
    for e in order_rows:
        assert isinstance(e.get("acct_ordinal"), int)
        assert e["symbol"] in ("BTCUSDT", "ETHUSDT")
    # Ordinals are the canonical sorted-distinct map: accA=1, accB=2.
    ords = {e["account_id"]: e["acct_ordinal"] for e in order_rows}
    assert ords == {"accA": 1, "accB": 2}


@pytest.mark.asyncio
async def test_orchestrator_emit_complete_false_defers_terminal():
    # FR-036: with emit_complete=False the orchestrator must NOT emit the terminal
    # "complete" event — the call-site emits it after the final DB commit.
    configs = [_cfg("accA")]
    results = _results("BTC")
    prog = RecordingProgress()
    ex, _accounts, _close = build_executor(configs, progress=prog, scan_id="scan-1")

    await ex.run_post_scan_tail(results, emit_complete=False)
    stages = [e["stage"] for e in prog.events]
    assert "complete" not in stages, "terminal must be deferred when emit_complete=False"

    # The call-site then emits it explicitly.
    ex.emit_tail_complete()
    assert prog.events[-1]["stage"] == "complete"
    assert prog.events[-1]["status"] == "done"
    assert prog.events[-1]["pct"] == 100

    # The live per-account "done" row counters must equal the terminal summary totals.
    configs = [_cfg("accA", max_trades=2)]
    results = _results("BTC", "ETH", "SOL")
    prog = RecordingProgress()
    ex, _accounts, _close = build_executor(configs, progress=prog, scan_id="scan-1")
    out = await ex.run_post_scan_tail(results)

    summary = {s["account_id"]: s for s in out["summaries"]}["accA"]
    # Last per-account done row for accA (stage=batch, status=done, no symbol).
    acct_done = [
        e for e in prog.events
        if e["stage"] == "batch" and e.get("status") == "done" and not e.get("symbol")
        and e.get("account_id") == "accA"
    ]
    assert acct_done, "expected a per-account done row"
    last = acct_done[-1]
    assert last["trades_executed"] == summary["trades_executed"]
    assert last["trades_skipped"] == summary["trades_skipped"]


@pytest.mark.asyncio
async def test_run_stage_persists_partial_on_ban_and_continues():
    # R2: a RateGateBanAbort in one stage drains the partial merge (placed orders) and
    # persists it, and the tail still completes (per-stage isolation preserved).
    from backend.services.bybit_rate_gate import RateGateBanAbort

    psc.configure_account_concurrency(1)

    class BanOnEthBatch(RecordingAccountsService):
        async def place_trade(self, **kwargs):
            if kwargs["symbol"] == "ETHUSDT":
                raise RateGateBanAbort("banned")
            return await super().place_trade(**kwargs)

    accounts = BanOnEthBatch()
    from backend.services.auto_trade_service import AutoTradeExecutor
    ex = AutoTradeExecutor(accounts, None, scan_id="scan-ban2")
    ex.init_configs([_cfg("accA", max_trades=5)])
    for st in ex._state.values():
        st.base_capital = 1000.0

    persisted_stages = []

    async def persist_cb(stage, execs):
        persisted_stages.append((stage, [e.symbol for e in execs]))

    out = await ex.run_post_scan_tail(_results("BTC", "ETH"), persist_cb=persist_cb)
    # BTC placed before the ban must be persisted under execute_batch.
    batch_persists = [syms for (stage, syms) in persisted_stages if stage == "execute_batch"]
    assert any("BTCUSDT" in syms for syms in batch_persists)
    # The tail completed (summaries present) -- the ban did not crash it.
    assert out["summaries"]


@pytest.mark.asyncio
async def test_ban_emits_substatus_and_cooloff_for_panel():
    # TASK-3.2 (R1 fix): a RateGateBanAbort during a stage must EMIT a progress event
    # carrying substatus="ban" + cooloff_until so the live panel shows the cooloff
    # countdown (distinct from a micro-throttle). Otherwise the ban UX is dead code.
    from backend.services.bybit_rate_gate import RateGateBanAbort
    from backend.services.auto_trade_service import AutoTradeExecutor

    psc.configure_account_concurrency(1)
    COOLOFF = 1_700_000_000.0

    class BanWithCooloff(RecordingAccountsService):
        async def place_trade(self, **kwargs):
            raise RateGateBanAbort(cooloff_until=COOLOFF)

    prog = RecordingProgress()
    accounts = BanWithCooloff()
    ex = AutoTradeExecutor(accounts, None, progress=prog, scan_id="scan-ban-emit")
    ex.init_configs([_cfg("accA")])
    for st in ex._state.values():
        st.base_capital = 1000.0

    await ex.run_post_scan_tail(_results("BTC"))
    ban_events = [e for e in prog.events if e.get("substatus") == "ban"]
    assert ban_events, "a ban must emit a substatus='ban' progress event for the panel"
    assert ban_events[0].get("cooloff_until") == COOLOFF


def test_wire_reason_code_strips_free_text():
    # FR-045/R119: a stopped_reason carrying raw exception text must be coerced to a
    # safe code prefix before it crosses the WS wire (no free-text leak).
    from backend.services.auto_trade_service import _wire_reason_code

    assert _wire_reason_code("max_trades_reached") == "max_trades_reached"
    assert _wire_reason_code("wallet_fetch_failed: GET https://api?key=secret 500") == "wallet_fetch_failed"
    assert _wire_reason_code("positions_fetch_failed: timeout to 1.2.3.4:443") == "positions_fetch_failed"
    assert _wire_reason_code(None) is None
    assert _wire_reason_code("") is None


@pytest.mark.asyncio
async def test_emitted_account_event_scrubs_free_text_reason_code():
    # Integration: the per-account done emit must apply _wire_reason_code so a free-text
    # stopped_reason (raw exception) never reaches the progress event. Pins the emit
    # SITE, not just the helper — reverting reason_code=_wire_reason_code(...) to a raw
    # stopped_reason would fail this.
    from backend.services.auto_trade_service import AutoTradeExecutor

    psc.configure_account_concurrency(1)
    prog = RecordingProgress()
    accounts = RecordingAccountsService()
    ex = AutoTradeExecutor(accounts, None, progress=prog, scan_id="scrub-1")
    ex.init_configs([_cfg("accA")])
    state = list(ex._state.values())[0]
    state.base_capital = 1000.0
    # Seed a free-text exception stop reason (the leak vector).
    state.stopped = True
    state.stopped_reason = "wallet_fetch_failed: GET https://api.bybit.com?api_key=SECRET 500"

    await ex.run_post_scan_tail(_results("BTC"))
    # No emitted event's reason_code may contain the free-text/secret tail.
    for e in prog.events:
        rc = e.get("reason_code")
        if rc is not None:
            assert "SECRET" not in rc and "https" not in rc and ":" not in rc, (
                f"free-text leaked via reason_code on the wire: {rc!r}"
            )
    # The scrubbed code prefix IS present on the per-account row.
    acct_codes = [e.get("reason_code") for e in prog.events if e.get("acct_ordinal") == 1]
    assert "wallet_fetch_failed" in acct_codes



