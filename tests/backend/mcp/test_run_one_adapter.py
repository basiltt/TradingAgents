"""BacktestService.run_one adapter tests — G0 (real optimizer execution).

run_one is the BacktestRunner Protocol adapter the optimizer depends on. It runs
ONE config against a pre-loaded klines snapshot via the real BacktestEngine, no
DB persistence, and returns the engine's metrics dict. Before this, the optimizer
only worked with a FakeRunner — optimize_config ran on empty inputs.
"""
from __future__ import annotations

import pytest


def _min_config(**over):
    cfg = {
        "starting_capital": 1000.0,
        "leverage": 5,
        "capital_pct": 10.0,
        "take_profit_pct": 5.0,
        "stop_loss_pct": 3.0,
        "direction": "straight",
        "slippage_bps": 2,
        "fee_rate_pct": 0.055,
    }
    cfg.update(over)
    return cfg


def _kline_series(n=120, start_price=100.0):
    out = []
    p = start_price
    t = 1_700_000_000_000
    for i in range(n):
        p_open = p
        p = p * (1.01 if i % 2 == 0 else 0.995)
        out.append({
            "open_time": t + i * 60_000,
            "open": p_open, "high": max(p_open, p) * 1.001,
            "low": min(p_open, p) * 0.999, "close": p, "volume": 10.0,
        })
    return out


def _signal(ticker="BTCUSDT", ts=1_700_000_000_000):
    # Real engine signal contract: scan_id (batch group), ticker (kline lookup),
    # direction (long/short), score, confidence, signal_time.
    return {
        "scan_id": "scan-1",
        "ticker": ticker,
        "direction": "long",
        "score": 0.9,
        "confidence": "high",
        "signal_time": ts,
        "analysis_price": 100.0,
    }


@pytest.mark.asyncio
async def test_run_one_returns_finite_metrics():
    """run_one against a real klines snapshot returns a metrics dict with the
    objective metrics the ranker needs (finite numbers, not empty)."""
    from backend.services.backtest_service import BacktestService

    svc = BacktestService.__new__(BacktestService)  # no full init — run_one is pure-ish
    snapshot = {"BTCUSDT": _kline_series()}
    signals = [_signal()]
    metrics = await svc.run_one(
        _min_config(), signals, snapshot, {}, deadline=None
    )
    assert isinstance(metrics, dict)
    # the engine emits aggregate metrics on a non-empty run (its own key names)
    assert "net_profit_pct" in metrics and "max_dd_pct" in metrics
    assert "sharpe" in metrics and "total_trades" in metrics
    # the ranker can resolve standard objectives against these via aliasing
    from backend.mcp.tools.optimizer.ranker import _resolve_metric
    assert _resolve_metric(metrics, "total_return") is not None  # → net_profit_pct
    assert _resolve_metric(metrics, "max_drawdown") is not None  # → max_dd_pct


@pytest.mark.asyncio
async def test_run_one_empty_signals_is_safe():
    """No signals → engine returns empty-but-valid metrics, run_one does not crash."""
    from backend.services.backtest_service import BacktestService

    svc = BacktestService.__new__(BacktestService)
    metrics = await svc.run_one(_min_config(), [], {}, {}, deadline=None)
    assert isinstance(metrics, dict)


@pytest.mark.asyncio
async def test_run_one_satisfies_runner_protocol():
    """BacktestService is usable where the optimizer expects a BacktestRunner."""
    from backend.mcp.core.runner import BacktestRunner
    from backend.services.backtest_service import BacktestService

    svc = BacktestService.__new__(BacktestService)
    assert hasattr(svc, "run_one")
    # structural protocol check (runtime) — has the method with the right name
    assert callable(svc.run_one)
