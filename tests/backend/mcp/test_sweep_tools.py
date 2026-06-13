"""Async sweep tool tests — G1 (FR-021/040), real DB sweep_repo."""
from __future__ import annotations

import asyncio

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import _REGISTRY
from backend.mcp.discovery import discover_tools

discover_tools()


class _Runner:
    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        lev = float(config.get("leverage", 1))
        return {"net_profit_pct": lev * 2, "max_dd_pct": 30.0 - lev, "sharpe": lev,
                "total_trades": 40, "top_trade_pnl_share": 0.2, "expectancy": 1.0}


class _LoadInputsRunner(_Runner):
    """Runner with load_inputs that records the date_range_* values it receives,
    so a test can assert sweep_run coerced the agent's ISO strings to datetimes
    before they hit asyncpg's timestamptz binds."""

    def __init__(self):
        self.seen_dates: list[tuple] = []

    async def load_inputs(self, config):
        self.seen_dates.append(
            (config.get("date_range_start"), config.get("date_range_end"))
        )
        return [], {}, {}


class _ConfigCapturingRunner(_Runner):
    """Records every combo config run_one receives, so a test can assert the
    background body seeded starting_capital into combos even with NO base."""

    def __init__(self):
        self.seen_configs: list[dict] = []

    async def load_inputs(self, config):
        # one signal/symbol so the sweep has something to run
        return ([{"scan_id": "s1", "ticker": "BTCUSDT"}],
                {"BTCUSDT": [{"open_time": 1, "close": 100.0}]},
                {"BTCUSDT": {"qty_step": 0.001}})

    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        self.seen_configs.append(dict(config))
        return await super().run_one(config, signals, snapshot, instrument_info,
                                     deadline=deadline)


class _BoomRunner(_Runner):
    """run_one raises, so a test can assert the failure is recorded with an
    error_message (not a silent 'failed')."""

    async def load_inputs(self, config):
        return ([{"scan_id": "s1", "ticker": "BTCUSDT"}],
                {"BTCUSDT": [{"open_time": 1, "close": 100.0}]}, {})

    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        raise RuntimeError("combo blew up")



class _State:
    """Minimal app.state stand-in carrying the real sweep_repo + a task registry."""
    def __init__(self, repo, runner=None):
        self.mcp_sweep_repo = repo
        self.backtest_runner = runner or _Runner()
        self.mcp_backtest_runner = runner or _Runner()
        self.db = None


class _Services:
    def __init__(self, repo, runner=None):
        self._state = _State(repo, runner)
        self.sweep_repo = repo
        self.backtest_runner = runner or _Runner()
        self.db = None


def _ctx(repo, runner=None):
    return CallContext(principal="t", session_id="s", tier="BACKTEST",
                       correlation_id=None, services=_Services(repo, runner), clock=RealClock())


async def _call(name, args, ctx):
    return await dispatch(_REGISTRY[name], args, ctx, audit=lambda x: None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_run_status_results_lifecycle(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    ctx = _ctx(repo)

    # launch
    r = await _call("sweep_run", {"space": {"leverage": [5, 10, 20]},
                                  "objective": "total_return", "strategy": "grid"}, ctx)
    assert r["isError"] is False
    sweep_id = r["structuredContent"]["sweep_id"]
    assert r["structuredContent"]["total_combos"] == 3

    # wait for the background task to finish (it's tracked on _state)
    task = ctx.services._state.mcp_sweep_tasks[sweep_id]
    await task

    # status → completed
    s = await _call("sweep_status", {"sweep_id": sweep_id}, ctx)
    assert s["structuredContent"]["status"] == "completed"
    assert s["structuredContent"]["completed_combos"] == 3

    # results ranked by total_return → leverage 20 (net_profit_pct 40) is best
    res = await _call("sweep_results", {"sweep_id": sweep_id, "objective": "total_return"}, ctx)
    rows = res["structuredContent"]["results"]
    assert rows[0]["config"]["leverage"] == 20

    # re-rank by max_drawdown (minimize) → leverage 20 has the LOWEST max_dd (30-20=10)
    res2 = await _call("sweep_results", {"sweep_id": sweep_id, "objective": "max_drawdown"}, ctx)
    assert res2["structuredContent"]["results"][0]["config"]["leverage"] == 20
    assert res2["structuredContent"]["reranked_by"] == "max_drawdown"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_run_rejects_oversized(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    ctx = _ctx(SweepRepository(mcp_pool))
    big = {f"p{i}": list(range(10)) for i in range(6)}  # 10^6 combos
    r = await _call("sweep_run", {"space": big, "strategy": "grid"}, ctx)
    assert r["isError"] is True  # MCPValidationError (over cap)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_cancel(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    # create a running job directly, then cancel via the tool
    sid = await repo.create_job(strategy="grid", param_space={"x": [1, 2]},
                                objective_metric="sharpe", total_combos=2)
    ctx = _ctx(repo)
    c = await _call("sweep_cancel", {"sweep_id": sid}, ctx)
    assert c["structuredContent"]["cancelled"] is True
    assert (await repo.get_job(sid))["status"] == "cancelled"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_run_coerces_iso_string_dates_to_datetime(mcp_pool):
    """Regression: a date window arrives as ISO STRINGS. sweep_run must coerce
    them to tz-aware datetimes before load_inputs binds them to asyncpg
    timestamptz params — otherwise asyncpg raises 'expected datetime, got str'
    and the sweep loads zero signals."""
    from datetime import datetime, timezone

    from backend.mcp.repositories.sweep_repo import SweepRepository

    runner = _LoadInputsRunner()
    repo = SweepRepository(mcp_pool)
    ctx = _ctx(repo, runner)

    r = await _call("sweep_run", {
        "space": {"leverage": [5, 10]}, "objective": "total_return", "strategy": "grid",
        "date_range_start": "2026-06-04T18:30:00Z", "date_range_end": "2026-06-13T03:00:00Z",
        "starting_capital": 1000.0,
    }, ctx)
    assert r["isError"] is False, r

    # load_inputs ran in the foreground (before the bg task), with coerced dates
    assert runner.seen_dates, "load_inputs was never called"
    start, end = runner.seen_dates[0]
    assert isinstance(start, datetime) and isinstance(end, datetime)
    assert start == datetime(2026, 6, 4, 18, 30, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)

    # let the background task settle so it doesn't leak into other tests
    sweep_id = r["structuredContent"]["sweep_id"]
    task = ctx.services._state.mcp_sweep_tasks.get(sweep_id)
    if task is not None:
        await task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_run_seeds_starting_capital_with_no_base(mcp_pool):
    """Regression: a sweep called with NO base must still complete. Each combo
    config has to carry starting_capital (the engine reads it as a required key);
    without seeding, the background body KeyErrors on the first combo and the
    sweep silently flips to 'failed' at 0 completed."""
    from backend.mcp.repositories.sweep_repo import SweepRepository

    runner = _ConfigCapturingRunner()
    repo = SweepRepository(mcp_pool)
    ctx = _ctx(repo, runner)

    r = await _call("sweep_run", {
        "space": {"leverage": [5, 10]}, "objective": "sharpe", "strategy": "grid",
        # NO "base" key — this is the call shape that used to fail
        "date_range_start": "2026-06-04T18:30:00Z", "date_range_end": "2026-06-13T03:00:00Z",
        "starting_capital": 234.0,
    }, ctx)
    assert r["isError"] is False, r
    sweep_id = r["structuredContent"]["sweep_id"]

    task = ctx.services._state.mcp_sweep_tasks.get(sweep_id)
    if task is not None:
        await task

    # sweep completed, not failed
    job = await repo.get_job(sweep_id)
    assert job["status"] == "completed", job
    assert job["completed_combos"] == 2
    # every combo the engine saw carried starting_capital (seeded from the arg)
    assert runner.seen_configs, "no combos ran"
    assert all(c.get("starting_capital") == 234.0 for c in runner.seen_configs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_failure_records_error_message(mcp_pool):
    """Regression: a combo that raises must record WHY on the job (error_message)
    instead of a silent 'failed' with no diagnosis. sweep_status surfaces it."""
    from backend.mcp.repositories.sweep_repo import SweepRepository

    runner = _BoomRunner()
    repo = SweepRepository(mcp_pool)
    ctx = _ctx(repo, runner)

    r = await _call("sweep_run", {
        "space": {"leverage": [5]}, "objective": "sharpe", "strategy": "grid",
        "date_range_start": "2026-06-04T18:30:00Z", "date_range_end": "2026-06-13T03:00:00Z",
        "starting_capital": 234.0,
    }, ctx)
    assert r["isError"] is False, r
    sweep_id = r["structuredContent"]["sweep_id"]

    task = ctx.services._state.mcp_sweep_tasks.get(sweep_id)
    if task is not None:
        await task

    # status surfaces the failure reason
    s = await _call("sweep_status", {"sweep_id": sweep_id}, ctx)
    sc = s["structuredContent"]
    assert sc["status"] == "failed"
    assert sc["error_message"] and "combo blew up" in sc["error_message"]
