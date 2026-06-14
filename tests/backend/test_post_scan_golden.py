"""Per-account partition / merge golden tests for execute_batch + fill (TASK-2.4/2.10).

These prove the refactored execute_batch / fill_immediate_remaining are
behavior-identical between the sequential (width=1) and parallel (width>=2) paths:
  * per-account ORDERED placement sequence equal at width 1 vs N
  * created-rule fingerprint equal
  * per-account trades_executed/failed/skipped equal
  * no double-placement of a symbol within an account
  * one account failing in isolation does not block the others
  * at width>=2 with multiple accounts, placements genuinely overlap (fan-out proof)

Width is set through the process-wide post_scan_concurrency singleton.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services import post_scan_concurrency as psc
from backend.services import post_scan_flags
from tests.backend.post_scan_harness import (
    RateAwareThrottle,
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


def _cfg(account_id, **overrides):
    base = {
        "account_id": account_id,
        "execution_mode": "batch",
        "max_trades": 5,
        "min_score": 0,
        "signal_sides": "both",
        "leverage": 10,
        "take_profit_pct": 150,
        "stop_loss_pct": 100,
        "capital_pct": 10,
        "direction": "straight",
        "confidence_filter": "any",
    }
    base.update(overrides)
    return base


def _results(*tickers):
    return [
        {"id": f"r{i}", "ticker": t, "status": "completed", "direction": "sell",
         "score": -(10 - i), "confidence": "high"}
        for i, t in enumerate(tickers)
    ]


async def _run_batch(configs, results, width):
    psc.configure_account_concurrency(width)
    # latency forces interleaving at width>1; harmless at width=1 (serialized).
    accounts = RecordingAccountsService(latency=0.002)
    close = RecordingCloseService()
    ex, accounts, close = build_executor(configs, accounts=accounts, close=close)
    await ex.execute_batch(results)
    return ex, accounts, close


@pytest.mark.asyncio
async def test_partition_golden_equality_width1_vs_width2():
    configs = [_cfg("accA"), _cfg("accB"), _cfg("accC")]
    results = _results("BTC", "ETH", "SOL", "XRP")

    ex1, acc1, close1 = await _run_batch([dict(c) for c in configs], results, width=1)
    ex2, acc2, close2 = await _run_batch([dict(c) for c in configs], results, width=2)

    # Per-account ordered placement tuples identical across widths.
    assert acc1.per_account_tuples() == acc2.per_account_tuples()
    # Each account placed all 4 symbols, best-|score|-first (BTC..XRP).
    for aid in ("accA", "accB", "accC"):
        syms = [p.symbol for p in acc1.placements[aid]]
        assert syms == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    # Per-account summaries identical.
    s1 = {s["account_id"]: (s["trades_executed"], s["trades_failed"], s["trades_skipped"]) for s in ex1.get_summaries()}
    s2 = {s["account_id"]: (s["trades_executed"], s["trades_failed"], s["trades_skipped"]) for s in ex2.get_summaries()}
    assert s1 == s2


@pytest.mark.asyncio
async def test_width2_actually_overlaps_across_accounts():
    configs = [_cfg("accA"), _cfg("accB"), _cfg("accC")]
    results = _results("BTC", "ETH", "SOL")
    _ex, acc, _close = await _run_batch(configs, results, width=2)
    # With 3 accounts and width 2, at least 2 placements were in flight at once.
    assert acc.max_concurrency >= 2


@pytest.mark.asyncio
async def test_width1_strictly_serial():
    configs = [_cfg("accA"), _cfg("accB"), _cfg("accC")]
    results = _results("BTC", "ETH", "SOL")
    _ex, acc, _close = await _run_batch(configs, results, width=1)
    assert acc.max_concurrency == 1


@pytest.mark.asyncio
async def test_no_double_placement_within_account():
    # max_trades binds; the same symbol must never be placed twice for one account.
    configs = [_cfg("accA", max_trades=2)]
    results = _results("BTC", "ETH", "SOL", "XRP")
    _ex, acc, _close = await _run_batch(configs, results, width=2)
    syms = [p.symbol for p in acc.placements["accA"]]
    assert syms == ["BTCUSDT", "ETHUSDT"]  # exactly 2, no repeats
    assert len(set(syms)) == len(syms)


@pytest.mark.asyncio
async def test_one_account_failure_isolated_from_others():
    # accB's place_trade always raises; accA and accC must still place everything.
    configs = [_cfg("accA"), _cfg("accB"), _cfg("accC")]
    results = _results("BTC", "ETH")

    psc.configure_account_concurrency(3)

    class FailingForB(RecordingAccountsService):
        async def place_trade(self, **kwargs):
            if kwargs["account_id"] == "accB":
                raise RuntimeError("boom for accB")
            return await super().place_trade(**kwargs)

    accounts = FailingForB(latency=0.001)
    close = RecordingCloseService()
    ex, accounts, close = build_executor(configs, accounts=accounts, close=close)
    await ex.execute_batch(results)

    # accA + accC fully placed; accB recorded nothing (all failed) but did not crash
    # the others.
    assert [p.symbol for p in accounts.placements.get("accA", [])] == ["BTCUSDT", "ETHUSDT"]
    assert [p.symbol for p in accounts.placements.get("accC", [])] == ["BTCUSDT", "ETHUSDT"]
    assert accounts.placements.get("accB", []) == []
    by_acct = {s["account_id"]: s for s in ex.get_summaries()}
    assert by_acct["accA"]["trades_executed"] == 2
    assert by_acct["accC"]["trades_executed"] == 2
    # accB counted failures, not successes.
    assert by_acct["accB"]["trades_executed"] == 0
    assert by_acct["accB"]["trades_failed"] >= 1


@pytest.mark.asyncio
async def test_fill_to_max_partition_golden_equality():
    # min_score gate leaves a backfill gap that fill_to_max closes; both widths equal.
    configs = [
        _cfg("accA", max_trades=3, min_score=8, fill_to_max_trades=True),
        _cfg("accB", max_trades=3, min_score=8, fill_to_max_trades=True),
    ]
    # scores: 10,9,8,7,6 -> only first 3 pass min_score=8 strictly; fill adds the rest
    results = _results("AAA", "BBB", "CCC", "DDD", "EEE")

    ex1, acc1, _ = await _run_batch([dict(c) for c in configs], results, width=1)
    ex2, acc2, _ = await _run_batch([dict(c) for c in configs], results, width=2)
    assert acc1.per_account_tuples() == acc2.per_account_tuples()
    # Each account filled to max_trades=3.
    for aid in ("accA", "accB"):
        assert len(acc1.placements[aid]) == 3


@pytest.mark.asyncio
async def test_multi_config_same_account_dedup_preserved():
    # Two batch configs on the SAME account, max_trades=1 each: a symbol placed by
    # config A must not be re-placed by config B (shared per-account traded set).
    configs = [
        _cfg("accA", max_trades=1, min_score=7, fill_to_max_trades=True),
        _cfg("accA", max_trades=1, min_score=7, fill_to_max_trades=True),
    ]
    results = _results("MEGA", "HIGH")  # scores -10, -9

    ex1, acc1, _ = await _run_batch([dict(c) for c in configs], results, width=1)
    ex2, acc2, _ = await _run_batch([dict(c) for c in configs], results, width=2)
    assert acc1.per_account_tuples() == acc2.per_account_tuples()
    syms = sorted(p.symbol for p in acc1.placements["accA"])
    assert syms == ["HIGHUSDT", "MEGAUSDT"]  # each placed once, no duplicate


# --------------------------------------------------------------------------- #
# Full-tail golden equality (init_balances rule creation + cleanup + skip codes)
# --------------------------------------------------------------------------- #

def _rule_cfg(account_id, **overrides):
    base = _cfg(
        account_id,
        target_goal_type="profit_pct", target_goal_value=10,
        max_drawdown_pct=5, breakeven_timeout_hours=2,
        max_trade_duration_hours=4, trailing_profit_pct=3,
    )
    base.update(overrides)
    return base


async def _run_full_tail(configs, results, width):
    psc.configure_account_concurrency(width)
    accounts = RecordingAccountsService(latency=0.001)
    close = RecordingCloseService()
    from backend.services.auto_trade_service import AutoTradeExecutor
    ex = AutoTradeExecutor(accounts, close, scan_id=f"scan-w{width}")
    ex.init_configs([dict(c) for c in configs])
    await ex.init_balances()  # creates close rules per account
    out = await ex.run_post_scan_tail(results)
    return ex, accounts, close, out


@pytest.mark.asyncio
async def test_full_tail_golden_rules_and_summaries_width_invariant():
    configs = [_rule_cfg("accA"), _rule_cfg("accB")]
    results = _results("BTC", "ETH", "SOL")

    ex1, acc1, close1, out1 = await _run_full_tail(configs, results, width=1)
    ex2, acc2, close2, out2 = await _run_full_tail(configs, results, width=2)

    # 1) Per-account ordered placements identical.
    assert acc1.per_account_tuples() == acc2.per_account_tuples()
    # 2) Created-rule fingerprint identical (each account got the same rules in order).
    assert close1.created_rule_fingerprint() == close2.created_rule_fingerprint()
    # Each account created 5 rules (rise/drawdown/breakeven/duration/trailing).
    for aid in ("accA", "accB"):
        assert len(close1.created.get(aid, [])) == 5
    # 3) Deleted rules identical (cleanup deletes for zero-trade accounts only — here
    #    both traded, so nothing deleted).
    assert close1.deleted == close2.deleted
    # 4) Per-account summary counters identical.
    s1 = {s["account_id"]: (s["trades_executed"], s["trades_failed"], s["trades_skipped"]) for s in out1["summaries"]}
    s2 = {s["account_id"]: (s["trades_executed"], s["trades_failed"], s["trades_skipped"]) for s in out2["summaries"]}
    assert s1 == s2


@pytest.mark.asyncio
async def test_full_tail_golden_cleanup_deletes_zero_trade_rules_both_widths():
    # An account with NO qualifying signals (whitelist blocks all) creates rules in
    # init then has them deleted by cleanup — identically at width 1 and 2.
    configs = [
        _rule_cfg("accTrade"),
        _rule_cfg("accIdle", symbol_whitelist=["NOTHINGUSDT"]),  # nothing passes
    ]
    results = _results("BTC", "ETH")

    _ex1, _acc1, close1, _o1 = await _run_full_tail(configs, results, width=1)
    _ex2, _acc2, close2, _o2 = await _run_full_tail(configs, results, width=2)

    # accIdle placed nothing => its 5 rules are all deleted by cleanup; accTrade keeps.
    assert sorted(close1.deleted.get("accIdle", [])) == sorted(r["id"] for r in close1.created["accIdle"])
    assert "accTrade" not in close1.deleted
    # Width-invariant.
    assert {k: sorted(v) for k, v in close1.deleted.items()} == {k: sorted(v) for k, v in close2.deleted.items()}


@pytest.mark.asyncio
async def test_post_scan_recheck_width_invariant():
    # Two accounts that were skipped (positions_already_open) but are now clear get
    # rescued by the recheck. Parallelizing the per-account recheck must produce the
    # same placements + summaries at width 1 and 2.
    async def _run(width):
        psc.configure_account_concurrency(width)
        accounts = RecordingAccountsService(latency=0.001)
        accounts.positions_by_account = {}  # all clear now
        close = RecordingCloseService()
        from backend.services.auto_trade_service import AutoTradeExecutor
        ex = AutoTradeExecutor(accounts, close, scan_id=f"rc-{width}")
        configs = [
            _cfg("accA", max_trades=2, target_goal_type="profit_pct", target_goal_value=10),
            _cfg("accB", max_trades=2, target_goal_type="profit_pct", target_goal_value=10),
        ]
        ex.init_configs(configs)
        # Simulate both accounts having been stopped for positions_already_open.
        for st in ex._state.values():
            st.stopped = True
            st.stopped_reason = "positions_already_open"
            st.base_capital = 1000.0
        results = _results("BTC", "ETH", "SOL")
        execs = await ex.post_scan_recheck(results)
        return accounts, execs

    acc1, ex1 = await _run(1)
    acc2, ex2 = await _run(2)
    assert acc1.per_account_tuples() == acc2.per_account_tuples()
    # Both accounts rescued and placed up to max_trades=2.
    for aid in ("accA", "accB"):
        assert len(acc1.placements.get(aid, [])) == 2


@pytest.mark.asyncio
async def test_full_parallel_tail_green_in_no_services_mode():
    # TASK-2.9: the full parallel tail must run green with NO progress sink, NO
    # scan_id, NO close_svc, NO position_lock_registry (backtest / minimal mode).
    psc.configure_account_concurrency(3)
    from backend.services.auto_trade_service import AutoTradeExecutor
    accounts = RecordingAccountsService(latency=0.001)
    ex = AutoTradeExecutor(accounts, None)  # close_svc=None, no progress/scan_id/registry
    ex.init_configs([_cfg("accA"), _cfg("accB"), _cfg("accC")])
    for st in ex._state.values():
        st.base_capital = 1000.0
    out = await ex.run_post_scan_tail(_results("BTC", "ETH"))
    assert out["summaries"]
    assert len(accounts.placement_log) == 6  # 3 accounts x 2 symbols


@pytest.mark.asyncio
async def test_cancel_mid_tail_persists_placed_orders():
    # TASK-2.9: cancelling the tail task mid-flight must not lose orders already placed
    # (the per-account merge reads from slots populated as each account completes). A
    # CancelledError propagates out of the fan-out (cooperative stop).
    psc.configure_account_concurrency(1)  # serialize so accA completes before accB starts
    from backend.services.auto_trade_service import AutoTradeExecutor

    class SlowAfterA(RecordingAccountsService):
        async def place_trade(self, **kwargs):
            # Make accB's placements hang so we can cancel mid-tail.
            if kwargs["account_id"] == "accB":
                await asyncio.sleep(10)
            return await super().place_trade(**kwargs)

    accounts = SlowAfterA(latency=0.0)
    ex = AutoTradeExecutor(accounts, None)
    ex.init_configs([_cfg("accA"), _cfg("accB")])
    for st in ex._state.values():
        st.base_capital = 1000.0

    task = asyncio.create_task(ex.execute_batch(_results("BTC", "ETH")))
    await asyncio.sleep(0.05)  # let accA finish, accB hang
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # accA's orders were recorded by the exchange double despite the cancel.
    assert [p.symbol for p in accounts.placements.get("accA", [])] == ["BTCUSDT", "ETHUSDT"]


@pytest.mark.asyncio
async def test_placed_orders_survive_midaccount_ban_abort():
    # HIGH-1 (review R1): an account that raises RateGateBanAbort AFTER placing some
    # orders must NOT lose those orders from the merge — they hit the exchange and must
    # be recorded in auto_trade_results. The fan-out publishes each account's slot in a
    # finally, merges BEFORE re-raising, and the orchestrator drains the partial merge.
    from backend.services.auto_trade_service import AutoTradeExecutor
    from backend.services.bybit_rate_gate import RateGateBanAbort

    psc.configure_account_concurrency(1)

    class BanAfterFirst(RecordingAccountsService):
        async def place_trade(self, **kwargs):
            # accA: place BTC, then ban on the 2nd placement (ETH). accB: all fine.
            if kwargs["account_id"] == "accA" and kwargs["symbol"] == "ETHUSDT":
                raise RateGateBanAbort("order lane banned")
            return await super().place_trade(**kwargs)

    accounts = BanAfterFirst(latency=0.0)
    ex = AutoTradeExecutor(accounts, None, scan_id="scan-ban")
    ex.init_configs([_cfg("accA", max_trades=5), _cfg("accB", max_trades=5)])
    for st in ex._state.values():
        st.base_capital = 1000.0

    persisted: list = []

    async def persist_cb(stage, execs):
        persisted.extend(execs)

    # The orchestrator drains the partial merge on the ban — the tail does NOT crash.
    out = await ex.run_post_scan_tail(_results("BTC", "ETH", "SOL"), persist_cb=persist_cb)

    # accA placed BTC before the ban → it must be in the exchange record AND persisted.
    assert "BTCUSDT" in [p.symbol for p in accounts.placements.get("accA", [])]
    persisted_success = [e for e in persisted if e.status == "success"]
    persisted_symbols = {e.symbol for e in persisted_success}
    assert "BTCUSDT" in persisted_symbols, "accA's pre-ban order was lost from persistence (HIGH-1)"
    # accB (no ban) completed fully — its UNIQUE symbols (ETH, SOL beyond accA's reach)
    # must also be persisted, proving the non-banned account isn't dropped by the merge.
    assert {"ETHUSDT", "SOLUSDT"} <= persisted_symbols, "accB's orders were lost from the merge"
    assert "BTCUSDT" in [p.symbol for p in accounts.placements.get("accB", [])]
    # No DOUBLE-persist: BTC was placed once per account (accA + accB) => exactly 2
    # successful BTC rows, never more (a stale-merge drain would duplicate).
    btc_rows = [e for e in persisted_success if e.symbol == "BTCUSDT"]
    assert len(btc_rows) == 2, f"expected 2 BTC rows (one per account), got {len(btc_rows)}"
    # accB placed all 3 unique symbols exactly once each.
    for sym in ("ETHUSDT", "SOLUSDT"):
        assert len([e for e in persisted_success if e.symbol == sym]) == 1


@pytest.mark.asyncio
async def test_stray_child_cancel_does_not_tear_down_healthy_tail():
    # R3 (H-B): a CancelledError captured as a per-CHILD gather result (the parent task
    # is healthy) must NOT cancel the whole tail — the fan-out logs it and continues,
    # other accounts' orders are merged, and the tail finalizes normally.
    from backend.services.auto_trade_service import AutoTradeExecutor

    psc.configure_account_concurrency(2)

    class CancelAccB(RecordingAccountsService):
        async def place_trade(self, **kwargs):
            if kwargs["account_id"] == "accB":
                # Simulate this single account's task being cancelled mid-flight while
                # the parent tail is healthy.
                raise asyncio.CancelledError()
            return await super().place_trade(**kwargs)

    accounts = CancelAccB(latency=0.001)
    ex = AutoTradeExecutor(accounts, None, scan_id="scan-stray")
    ex.init_configs([_cfg("accA"), _cfg("accB"), _cfg("accC")])
    for st in ex._state.values():
        st.base_capital = 1000.0

    # The tail must NOT raise — accB's stray cancel is isolated; accA + accC complete.
    out = await ex.run_post_scan_tail(_results("BTC", "ETH"))
    assert out["summaries"], "tail should finalize despite a stray child cancel"
    assert [p.symbol for p in accounts.placements.get("accA", [])] == ["BTCUSDT", "ETHUSDT"]
    assert [p.symbol for p in accounts.placements.get("accC", [])] == ["BTCUSDT", "ETHUSDT"]
    assert accounts.placements.get("accB", []) == []






