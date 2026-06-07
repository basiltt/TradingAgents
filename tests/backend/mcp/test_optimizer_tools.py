"""Optimizer MCP tool tests — TASK-P4-07 (sweep_estimate, optimize_config)."""
from __future__ import annotations

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import _REGISTRY
from backend.mcp.discovery import discover_tools

discover_tools()


class _Runner:
    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        return {"sharpe": float(config.get("leverage", 1)), "total_return": float(config.get("leverage", 1)),
                "max_drawdown": 10.0, "total_trades": 40, "top_trade_pnl_share": 0.2, "expectancy": 1.0}


class _Services:
    def __init__(self, runner=None):
        self.backtest_runner = runner
        self.db = None
        self.backtest_service = None


def _ctx(runner=None):
    return CallContext(principal="t", session_id="s", tier="BACKTEST",
                       correlation_id=None, services=_Services(runner), clock=RealClock())


def test_optimizer_tools_registered():
    assert "sweep_estimate" in _REGISTRY
    assert "optimize_config" in _REGISTRY


@pytest.mark.asyncio
async def test_sweep_estimate_feasible_and_capped():
    spec = _REGISTRY["sweep_estimate"]
    r = await dispatch(spec, {"space": {"leverage": [5, 10, 20]}, "strategy": "grid"},
                       _ctx(), audit=lambda x: None)
    assert r["structuredContent"]["combo_count"] == 3
    assert r["structuredContent"]["feasible"] is True

    # oversized grid -> infeasible
    big = {f"p{i}": list(range(10)) for i in range(6)}
    r2 = await dispatch(spec, {"space": big, "strategy": "grid"}, _ctx(), audit=lambda x: None)
    assert r2["structuredContent"]["feasible"] is False


@pytest.mark.asyncio
async def test_optimize_config_proposes_winner():
    spec = _REGISTRY["optimize_config"]
    r = await dispatch(
        spec,
        {"space": {"leverage": [5, 20]}, "objective": "sharpe", "strategy": "grid"},
        _ctx(_Runner()), audit=lambda x: None,
    )
    assert r["isError"] is False, r
    sc = r["structuredContent"]
    assert sc["total_combos"] == 2
    assert sc["winner"] is not None  # no baseline supplied -> top is the winner
    assert "1%" in sc["fidelity_caveat"] or "approximate" in sc["fidelity_caveat"]


@pytest.mark.asyncio
async def test_optimize_config_rejects_unknown_objective():
    spec = _REGISTRY["optimize_config"]
    r = await dispatch(spec, {"space": {"leverage": [5]}, "objective": "bogus"},
                       _ctx(_Runner()), audit=lambda x: None)
    assert r["isError"] is True


@pytest.mark.asyncio
async def test_optimize_config_unavailable_without_runner():
    spec = _REGISTRY["optimize_config"]
    r = await dispatch(spec, {"space": {"leverage": [5]}, "objective": "sharpe"},
                       _ctx(None), audit=lambda x: None)
    assert r["isError"] is True


class _RealishRunner:
    """A runner that loads inputs once and runs each combo against them — exercises
    the real-data optimize_config path (load_inputs + run_one + baseline)."""

    def __init__(self):
        self.load_calls = 0
        self.seen_snapshots = []

    async def load_inputs(self, config):
        self.load_calls += 1
        signals = [{"scan_id": "s1", "ticker": "BTCUSDT", "direction": "long", "score": 0.9}]
        snapshot = {"BTCUSDT": [{"open_time": 1, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 5}]}
        return signals, snapshot, {"BTCUSDT": {"qty_step": 0.001}}

    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        # record that the LOADED snapshot (not empty) reached the runner
        self.seen_snapshots.append(snapshot)
        lev = float(config.get("leverage", 1))
        return {"net_profit_pct": lev * 2, "max_dd_pct": 8.0, "sharpe": lev,
                "total_trades": 40, "top_trade_pnl_share": 0.2, "expectancy": 1.0}


@pytest.mark.asyncio
async def test_optimize_config_real_data_path_loads_inputs_once():
    runner = _RealishRunner()
    spec = _REGISTRY["optimize_config"]
    r = await dispatch(spec, {
        "space": {"leverage": [5, 10]}, "objective": "total_return", "strategy": "grid",
        "base": {"leverage": 5}, "date_range_start": "2026-01-01", "date_range_end": "2026-02-01",
        "starting_capital": 1000.0,
    }, _ctx(runner), audit=lambda x: None)
    assert r["isError"] is False
    sc = r["structuredContent"]
    # inputs loaded exactly once for the whole sweep (not per combo)
    assert runner.load_calls == 1
    # every run_one (baseline + 2 combos) saw the LOADED snapshot, never empty
    assert runner.seen_snapshots and all("BTCUSDT" in s for s in runner.seen_snapshots)
    # a winner is produced and ranked by the aliased total_return (net_profit_pct)
    assert sc["winner"] is not None
    assert sc["total_combos"] == 2
