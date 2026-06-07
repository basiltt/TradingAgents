"""SweepRanker tests — TASK-P4-02 (constraints, ranking, verdict, uplift)."""
from __future__ import annotations

import math

import pytest

from backend.mcp.tools.optimizer.ranker import (
    OBJECTIVE_METRICS,
    RobustnessVerdict,
    compute_uplift,
    rank_results,
    robustly_beats,
    robustness_verdict,
)


def _r(config_hash, metrics):
    return {"config_hash": config_hash, "config": {}, "metrics": metrics}


def test_objective_metric_enum():
    assert "sharpe" in OBJECTIVE_METRICS
    assert "total_return" in OBJECTIVE_METRICS
    assert "max_drawdown" in OBJECTIVE_METRICS


def test_rank_by_objective_descending():
    results = [
        _r("a", {"sharpe": 1.0, "total_trades": 40, "max_drawdown": 10}),
        _r("b", {"sharpe": 2.5, "total_trades": 40, "max_drawdown": 10}),
        _r("c", {"sharpe": 1.8, "total_trades": 40, "max_drawdown": 10}),
    ]
    ranked = rank_results(results, objective="sharpe")
    assert [x["config_hash"] for x in ranked] == ["b", "c", "a"]
    assert ranked[0]["result_rank"] == 1


def test_constraints_exclude_violators_before_ranking():
    results = [
        _r("a", {"sharpe": 3.0, "total_trades": 5, "max_drawdown": 30}),   # too few trades + DD
        _r("b", {"sharpe": 1.5, "total_trades": 40, "max_drawdown": 10}),
    ]
    ranked = rank_results(results, objective="sharpe",
                          constraints={"min_trades": 30, "max_drawdown": 15})
    assert [x["config_hash"] for x in ranked] == ["b"]  # a excluded despite higher sharpe


def test_nan_inf_quarantined_last():
    results = [
        _r("a", {"sharpe": float("nan"), "total_trades": 40, "max_drawdown": 10}),
        _r("b", {"sharpe": 1.0, "total_trades": 40, "max_drawdown": 10}),
        _r("c", {"sharpe": float("inf"), "total_trades": 40, "max_drawdown": 10}),
    ]
    ranked = rank_results(results, objective="sharpe")
    # b (finite) ranks first; nan/inf sorted last, never crowned
    assert ranked[0]["config_hash"] == "b"


def test_deterministic_tiebreak_by_hash():
    results = [
        _r("zzz", {"sharpe": 1.0, "total_trades": 40, "max_drawdown": 10}),
        _r("aaa", {"sharpe": 1.0, "total_trades": 40, "max_drawdown": 10}),
    ]
    ranked = rank_results(results, objective="sharpe")
    # equal objective -> tie-break by config_hash ascending
    assert [x["config_hash"] for x in ranked] == ["aaa", "zzz"]


def test_max_drawdown_objective_minimizes():
    results = [
        _r("a", {"max_drawdown": 20, "total_trades": 40}),
        _r("b", {"max_drawdown": 8, "total_trades": 40}),
    ]
    ranked = rank_results(results, objective="max_drawdown")
    assert ranked[0]["config_hash"] == "b"  # lower DD is better


def test_compute_uplift():
    baseline = {"total_return": 10.0, "sharpe": 1.0, "max_drawdown": 15.0, "expectancy": 2.0}
    candidate = {"total_return": 18.0, "sharpe": 1.6, "max_drawdown": 12.0, "expectancy": 3.0}
    up = compute_uplift(candidate, baseline)
    assert up["delta_total_return"] == pytest.approx(8.0)
    assert up["delta_sharpe"] == pytest.approx(0.6)
    assert up["delta_max_drawdown"] == pytest.approx(-3.0)  # lower DD is an improvement


def test_robustness_verdict_grades():
    # all pass -> robust
    m_robust = {"total_trades": 50, "max_drawdown": 10, "top_trade_pnl_share": 0.2}
    v = robustness_verdict(m_robust, baseline_max_dd=15, min_trades=30, min_uplift_pct=5,
                           uplift_pct=8)
    assert v == RobustnessVerdict.ROBUST
    # hard fail (too few trades) -> fragile
    m_fragile = {"total_trades": 5, "max_drawdown": 10, "top_trade_pnl_share": 0.2}
    v2 = robustness_verdict(m_fragile, baseline_max_dd=15, min_trades=30, min_uplift_pct=5,
                            uplift_pct=8)
    assert v2 == RobustnessVerdict.FRAGILE
    # soft fail only (single-trade-dominated) -> moderate
    m_mod = {"total_trades": 50, "max_drawdown": 10, "top_trade_pnl_share": 0.6}
    v3 = robustness_verdict(m_mod, baseline_max_dd=15, min_trades=30, min_uplift_pct=5,
                            uplift_pct=8)
    assert v3 == RobustnessVerdict.MODERATE


def test_robustly_beats_full_bar():
    baseline = {"sharpe": 1.0, "max_drawdown": 15.0, "total_return": 10.0}
    # clears the bar: +>=5% objective, >=30 trades, no DD regression, verdict != fragile
    winner = {"sharpe": 1.5, "max_drawdown": 12.0, "total_trades": 50,
              "top_trade_pnl_share": 0.2, "total_return": 18.0}
    assert robustly_beats(winner, baseline, objective="total_return",
                          min_trades=30, min_uplift_pct=5)
    # fails: DD regression
    loser = {"sharpe": 1.5, "max_drawdown": 20.0, "total_trades": 50,
             "top_trade_pnl_share": 0.2, "total_return": 18.0}
    assert not robustly_beats(loser, baseline, objective="total_return",
                              min_trades=30, min_uplift_pct=5)
