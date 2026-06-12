"""Cool Off Time — Phase 3 gate / trigger / sweep tests (mock-based, no DB/exchange).

Covers AutoTradeExecutor._account_in_cooloff (fail-open, gate-time classify, pure-time),
the settings pre-pass clobber guard, trade_service._fire_cooloff (post-commit, never-raises,
task-ref held), and CooloffSweep loop resilience.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState


# ── gate: _account_in_cooloff ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_returns_false_when_no_repo():
    ex = AutoTradeExecutor(MagicMock())
    assert await ex._account_in_cooloff("acc") is False


@pytest.mark.asyncio
async def test_gate_cooling_true_calls_classify_then_reads_status():
    repo = MagicMock()
    repo.read_status = AsyncMock(return_value={"cooling": True})
    clf = MagicMock()
    clf.maybe_classify = AsyncMock()
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo, cooloff_classifier=clf)
    assert await ex._account_in_cooloff("acc") is True
    clf.maybe_classify.assert_awaited_once_with("acc")  # gate-time sync classify
    repo.read_status.assert_awaited_once_with("acc")


@pytest.mark.asyncio
async def test_gate_not_cooling_false():
    repo = MagicMock()
    repo.read_status = AsyncMock(return_value={"cooling": False})
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo,
                           cooloff_classifier=MagicMock(maybe_classify=AsyncMock()))
    assert await ex._account_in_cooloff("acc") is False


@pytest.mark.asyncio
async def test_gate_fail_open_on_repo_error():
    repo = MagicMock()
    repo.read_status = AsyncMock(side_effect=RuntimeError("db down"))
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo,
                           cooloff_classifier=MagicMock(maybe_classify=AsyncMock()))
    # fail-open: a degraded read must NOT halt trading
    assert await ex._account_in_cooloff("acc") is False


@pytest.mark.asyncio
async def test_gate_fail_open_on_classifier_error():
    repo = MagicMock()
    repo.read_status = AsyncMock(return_value={"cooling": True})
    clf = MagicMock()
    clf.maybe_classify = AsyncMock(side_effect=RuntimeError("boom"))
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo, cooloff_classifier=clf)
    # classifier raising propagates into the try/except -> fail-open False
    assert await ex._account_in_cooloff("acc") is False


# ── settings pre-pass clobber guard ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_prepass_upserts_only_when_tier_enabled():
    repo = MagicMock()
    repo.upsert_settings = AsyncMock()
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo)
    ex._state = {
        "a_0": _AccountState(config={"account_id": "a", "cooloff_on_failure_enabled": True,
                                     "cooloff_on_failure_minutes": 60}),
        "b_0": _AccountState(config={"account_id": "b"}),  # all-OFF -> must NOT upsert
    }
    await ex._upsert_cooloff_settings_prepass()
    # only account 'a' (a tier enabled) is upserted; 'b' is skipped (clobber guard)
    repo.upsert_settings.assert_awaited_once()
    assert repo.upsert_settings.await_args.args[0] == "a"


@pytest.mark.asyncio
async def test_prepass_dedupes_accounts():
    repo = MagicMock()
    repo.upsert_settings = AsyncMock()
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo)
    cfg = {"account_id": "a", "cooloff_on_success_enabled": True, "cooloff_on_success_minutes": 30}
    ex._state = {"a_0": _AccountState(config=dict(cfg)), "a_1": _AccountState(config=dict(cfg))}
    await ex._upsert_cooloff_settings_prepass()
    repo.upsert_settings.assert_awaited_once()  # one upsert for the single distinct account


@pytest.mark.asyncio
async def test_prepass_fail_open_on_upsert_error():
    repo = MagicMock()
    repo.upsert_settings = AsyncMock(side_effect=RuntimeError("db down"))
    ex = AutoTradeExecutor(MagicMock(), cooloff_repo=repo)
    ex._state = {"a_0": _AccountState(config={"account_id": "a", "cooloff_on_failure_enabled": True,
                                              "cooloff_on_failure_minutes": 60})}
    # must NOT raise (never abort the scan)
    await ex._upsert_cooloff_settings_prepass()


@pytest.mark.asyncio
async def test_prepass_noop_when_no_repo():
    ex = AutoTradeExecutor(MagicMock())  # no cooloff_repo
    ex._state = {"a_0": _AccountState(config={"account_id": "a", "cooloff_on_failure_enabled": True})}
    await ex._upsert_cooloff_settings_prepass()  # no-op, no error


# ── trade_service post-commit trigger ────────────────────────────────────────

@pytest.mark.asyncio
async def test_fire_cooloff_schedules_task_and_holds_ref():
    from backend.services.trade_service import TradeService
    svc = TradeService.__new__(TradeService)  # bypass __init__ DB deps
    svc._cooloff_classifier = None
    svc._cooloff_bg_tasks = set()
    ran = asyncio.Event()

    async def _classify(acc):
        ran.set()

    clf = MagicMock()
    clf.maybe_classify = _classify
    svc.set_cooloff_classifier(clf)
    svc._fire_cooloff("acc")
    assert len(svc._cooloff_bg_tasks) == 1  # ref held (not GC'd)
    await asyncio.wait_for(ran.wait(), timeout=1.0)
    await asyncio.sleep(0)  # let done_callback run
    assert len(svc._cooloff_bg_tasks) == 0  # discarded on done


@pytest.mark.asyncio
async def test_fire_cooloff_noop_without_classifier():
    from backend.services.trade_service import TradeService
    svc = TradeService.__new__(TradeService)
    svc._cooloff_classifier = None
    svc._cooloff_bg_tasks = set()
    svc._fire_cooloff("acc")  # no classifier -> no-op, no error
    assert len(svc._cooloff_bg_tasks) == 0


@pytest.mark.asyncio
async def test_fire_cooloff_scheduling_never_raises(monkeypatch):
    from backend.services import trade_service as ts_mod
    from backend.services.trade_service import TradeService
    svc = TradeService.__new__(TradeService)
    # Use a plain (non-async) stub so no un-awaited coroutine is created when
    # create_task is monkeypatched to raise.
    svc._cooloff_classifier = MagicMock(maybe_classify=MagicMock())
    svc._cooloff_bg_tasks = set()
    # make create_task raise -> the wrapper must swallow it (never break a committed close)
    monkeypatch.setattr(ts_mod.asyncio, "create_task", MagicMock(side_effect=RuntimeError("loop")))
    svc._fire_cooloff("acc")  # must not raise


# ── sweep resilience ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_once_calls_each_active_account_and_survives_errors():
    from backend.services.cooloff_sweep import CooloffSweep
    db = MagicMock()
    db.list_accounts = AsyncMock(return_value=[
        {"id": "a", "is_active": True},
        {"id": "b", "is_active": False},  # skipped
        {"id": "c", "is_active": True},
    ])
    calls = []

    async def _classify(acc):
        calls.append(acc)
        if acc == "a":
            raise RuntimeError("boom")  # one account error must not stop the loop

    clf = MagicMock()
    clf.maybe_classify = _classify
    sweep = CooloffSweep(db, clf, MagicMock())
    await sweep._sweep_once()
    assert calls == ["a", "c"]  # b skipped (inactive); c still processed after a's error
