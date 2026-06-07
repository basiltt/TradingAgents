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


class _State:
    """Minimal app.state stand-in carrying the real sweep_repo + a task registry."""
    def __init__(self, repo):
        self.mcp_sweep_repo = repo
        self.backtest_runner = _Runner()
        self.mcp_backtest_runner = _Runner()
        self.db = None


class _Services:
    def __init__(self, repo):
        self._state = _State(repo)
        self.sweep_repo = repo
        self.backtest_runner = _Runner()
        self.db = None


def _ctx(repo):
    return CallContext(principal="t", session_id="s", tier="BACKTEST",
                       correlation_id=None, services=_Services(repo), clock=RealClock())


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
