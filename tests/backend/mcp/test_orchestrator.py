"""SweepOrchestrator tests — TASK-P4-05 (with a FakeBacktestRunner)."""
from __future__ import annotations

import pytest

from backend.mcp.tools.optimizer.combos import config_hash


class FakeBacktestRunner:
    """Deterministic metrics keyed by a config field, for fast unit tests."""

    def __init__(self, metric_fn=None):
        self.calls = 0
        # default: higher leverage -> higher sharpe (so the winner is predictable)
        self._fn = metric_fn or (lambda cfg: {
            "sharpe": float(cfg.get("leverage", 1)),
            "total_return": float(cfg.get("leverage", 1)) * 2,
            "max_drawdown": 10.0,
            "total_trades": 40,
            "top_trade_pnl_share": 0.2,
            "expectancy": 1.0,
        })

    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        self.calls += 1
        return self._fn(config)


@pytest.mark.asyncio
async def test_orchestrator_runs_ranks_and_finds_winner():
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    runner = FakeBacktestRunner()
    space = {"leverage": [5, 10, 20]}
    result = await run_sweep_inproc(
        runner=runner,
        space=space,
        base={"capital_pct": 5.0},
        strategy="grid",
        objective="sharpe",
        signals=[],
        snapshot={},
        instrument_info={},
    )
    assert runner.calls == 3  # one per combo
    assert len(result["ranked"]) == 3
    # highest leverage (20) -> highest sharpe -> rank 1
    assert result["ranked"][0]["config"]["leverage"] == 20
    assert result["ranked"][0]["result_rank"] == 1


@pytest.mark.asyncio
async def test_orchestrator_applies_constraints():
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    # leverage 20 gives best sharpe but we cap trades; make 20 have too few trades
    def _fn(cfg):
        lev = cfg.get("leverage", 1)
        return {
            "sharpe": float(lev),
            "total_return": float(lev),
            "max_drawdown": 10.0,
            "total_trades": 5 if lev == 20 else 40,
            "top_trade_pnl_share": 0.2,
        }

    result = await run_sweep_inproc(
        runner=FakeBacktestRunner(_fn),
        space={"leverage": [5, 10, 20]},
        base={},
        strategy="grid",
        objective="sharpe",
        constraints={"min_trades": 30},
        signals=[],
        snapshot={},
        instrument_info={},
    )
    # 20 excluded (too few trades) -> winner is 10
    assert result["ranked"][0]["config"]["leverage"] == 10


@pytest.mark.asyncio
async def test_orchestrator_baseline_uplift_and_winner_record():
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    result = await run_sweep_inproc(
        runner=FakeBacktestRunner(),
        space={"leverage": [5, 20]},
        base={},
        strategy="grid",
        objective="sharpe",
        signals=[],
        snapshot={},
        instrument_info={},
        baseline_metrics={"sharpe": 1.0, "total_return": 2.0, "max_drawdown": 10.0, "expectancy": 1.0},
    )
    winner = result["winner"]
    assert winner is not None
    assert "uplift" in winner
    assert winner["uplift"]["delta_sharpe"] > 0


@pytest.mark.asyncio
async def test_orchestrator_null_result_when_nothing_beats_baseline():
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    # baseline is unbeatable (very high sharpe)
    result = await run_sweep_inproc(
        runner=FakeBacktestRunner(),
        space={"leverage": [5, 10]},
        base={},
        strategy="grid",
        objective="sharpe",
        signals=[],
        snapshot={},
        instrument_info={},
        baseline_metrics={"sharpe": 100.0, "total_return": 200.0, "max_drawdown": 5.0},
    )
    # no candidate robustly beats baseline -> keep current config, no winner
    assert result["winner"] is None
    assert result["keep_current"] is True


@pytest.mark.asyncio
async def test_orchestrator_deterministic_for_same_inputs():
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    kwargs = dict(space={"leverage": [5, 10, 20]}, base={}, strategy="grid",
                  objective="sharpe", signals=[], snapshot={}, instrument_info={})
    r1 = await run_sweep_inproc(runner=FakeBacktestRunner(), **kwargs)
    r2 = await run_sweep_inproc(runner=FakeBacktestRunner(), **kwargs)
    assert [x["config_hash"] for x in r1["ranked"]] == [x["config_hash"] for x in r2["ranked"]]
