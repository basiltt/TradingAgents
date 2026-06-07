"""Tests for the per-strategy metrics breakdown in the backtester (Phase 4).

compute_by_strategy groups closed trades by strategy_kind x direction so the results
UI can show trend vs mean-reversion performance separately (the validation goal of
the whole feature). compute_all_metrics surfaces it under the `by_strategy` key.
"""

from __future__ import annotations

from backend.services.backtest_metrics import compute_by_strategy, compute_all_metrics


def _t(strategy_kind="trend", side="Sell", pnl=10.0):
    return {"strategy_kind": strategy_kind, "side": side, "pnl": pnl,
            "entry_time": None, "exit_time": None}


def test_by_strategy_splits_trend_and_mr():
    trades = [
        _t("trend", "Sell", 10.0),
        _t("trend", "Sell", -4.0),
        _t("mean_reversion", "Sell", 6.0),
        _t("mean_reversion", "Buy", -2.0),
    ]
    out = compute_by_strategy(trades)
    # keyed by "strategy_kind:direction"
    assert out["trend:short"]["total_trades"] == 2
    assert out["trend:short"]["net_profit"] == 6.0
    assert out["mean_reversion:short"]["total_trades"] == 1
    assert out["mean_reversion:long"]["total_trades"] == 1
    assert out["mean_reversion:long"]["net_profit"] == -2.0


def test_by_strategy_win_rate():
    trades = [_t("mean_reversion", "Sell", 5.0), _t("mean_reversion", "Sell", -1.0)]
    out = compute_by_strategy(trades)
    assert out["mean_reversion:short"]["win_rate"] == 50.0


def test_by_strategy_missing_kind_defaults_trend():
    # A trade with no strategy_kind (legacy/trend) buckets under trend.
    trades = [{"side": "Sell", "pnl": 3.0}]
    out = compute_by_strategy(trades)
    assert "trend:short" in out
    assert out["trend:short"]["total_trades"] == 1


def test_by_strategy_empty():
    assert compute_by_strategy([]) == {}


def test_compute_all_metrics_includes_by_strategy():
    trades = [_t("trend", "Sell", 10.0), _t("mean_reversion", "Buy", -2.0)]
    equity = [{"ts": None, "equity": 10000.0, "drawdown_pct": 0.0}]
    m = compute_all_metrics(trades, equity, {"starting_capital": 10000.0})
    assert "by_strategy" in m
    assert "trend:short" in m["by_strategy"]
    assert "mean_reversion:long" in m["by_strategy"]


def test_all_trend_run_single_bucket():
    trades = [_t("trend", "Sell", 5.0), _t("trend", "Buy", 3.0)]
    out = compute_by_strategy(trades)
    assert set(out.keys()) == {"trend:short", "trend:long"}
