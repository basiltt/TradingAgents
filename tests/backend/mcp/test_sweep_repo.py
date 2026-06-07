"""SweepRepository tests — G1 (TASK-P4-12b), real DB."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_write_and_rerank(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    sid = await repo.create_job(
        strategy="grid", param_space={"leverage": [5, 10]},
        objective_metric="total_return", total_combos=2,
    )
    # two results with engine-shaped metrics
    await repo.write_result(sweep_id=sid, config={"leverage": 5}, config_hash="a" * 64,
                            metrics={"net_profit_pct": 5.0, "max_dd_pct": 10.0},
                            objective_value=5.0, result_rank=2)
    await repo.write_result(sweep_id=sid, config={"leverage": 10}, config_hash="b" * 64,
                            metrics={"net_profit_pct": 20.0, "max_dd_pct": 25.0},
                            objective_value=20.0, result_rank=1)

    job = await repo.get_job(sid)
    assert job["completed_combos"] == 2
    assert job["total_combos"] == 2

    # default order = stored rank (b first, rank 1)
    default_order = await repo.results(sid)
    assert default_order[0]["config_hash"] == "b" * 64

    # re-rank by max_drawdown (minimize) → the LOWER max_dd_pct wins (a: 10 < b: 25)
    by_dd = await repo.results(sid, objective="max_drawdown")
    assert by_dd[0]["config_hash"] == "a" * 64  # no re-run, server-side re-sort


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_result_is_idempotent(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    sid = await repo.create_job(strategy="grid", param_space={"x": [1]},
                                objective_metric="sharpe", total_combos=1)
    h = "c" * 64
    await repo.write_result(sweep_id=sid, config={"x": 1}, config_hash=h,
                            metrics={"sharpe": 1.0}, objective_value=1.0)
    # re-writing the same hash must not double-count completed_combos
    await repo.write_result(sweep_id=sid, config={"x": 1}, config_hash=h,
                            metrics={"sharpe": 1.5}, objective_value=1.5)
    job = await repo.get_job(sid)
    assert job["completed_combos"] == 1  # capped at total + idempotent upsert


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_keeps_partial_results(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    sid = await repo.create_job(strategy="grid", param_space={"x": [1, 2, 3]},
                                objective_metric="sharpe", total_combos=3)
    await repo.write_result(sweep_id=sid, config={"x": 1}, config_hash="d" * 64,
                            metrics={"sharpe": 1.0}, objective_value=1.0)
    assert await repo.cancel_job(sid) is True
    job = await repo.get_job(sid)
    assert job["status"] == "cancelled"
    assert len(await repo.results(sid)) == 1  # partial result preserved
    # cancelling again is a no-op (not running)
    assert await repo.cancel_job(sid) is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recover_interrupted_marks_running_sweeps(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    sid = await repo.create_job(strategy="grid", param_space={"x": [1]},
                                objective_metric="sharpe", total_combos=1)
    # job is 'running' (create_job sets it). Simulate a crash → boot recovery.
    n = await repo.recover_interrupted()
    assert n >= 1
    job = await repo.get_job(sid)
    assert job["status"] == "interrupted"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_config_hashes_for_resume(mcp_pool):
    from backend.mcp.repositories.sweep_repo import SweepRepository

    repo = SweepRepository(mcp_pool)
    sid = await repo.create_job(strategy="grid", param_space={"x": [1, 2]},
                                objective_metric="sharpe", total_combos=2)
    await repo.write_result(sweep_id=sid, config={"x": 1}, config_hash="e" * 64,
                            metrics={"sharpe": 1.0}, objective_value=1.0)
    done = await repo.completed_config_hashes(sid)
    assert "e" * 64 in done and len(done) == 1
