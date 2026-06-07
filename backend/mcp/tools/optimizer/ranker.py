"""SweepRanker — TASK-P4-02.

Pure ranking: exclude constraint-violators, sort by objective (NaN/Inf last,
deterministic tie-break by config_hash), compute uplift vs baseline, and grade a
robustness verdict. Reuses the project's metric conventions; no engine math here.
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Any, Optional

# Agent-selectable objective metrics (app-validated; no DB CHECK so additive
# metrics need no migration). "max_drawdown" is minimized; the rest maximized.
OBJECTIVE_METRICS: dict[str, str] = {
    "total_return": "max",
    "sharpe": "max",
    "sortino": "max",
    "max_drawdown": "min",
    "win_rate": "max",
    "profit_factor": "max",
    "expectancy": "max",
    "calmar": "max",
}


class RobustnessVerdict(str, Enum):
    ROBUST = "robust"
    MODERATE = "moderate"
    FRAGILE = "fragile"


def _objective_value(metrics: dict[str, Any], objective: str) -> Optional[float]:
    v = metrics.get(objective)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None  # quarantine
    return f


def _passes_constraints(metrics: dict[str, Any], constraints: dict[str, Any]) -> bool:
    if not constraints:
        return True
    if "min_trades" in constraints and float(metrics.get("total_trades", 0)) < constraints["min_trades"]:
        return False
    if "max_drawdown" in constraints and float(metrics.get("max_drawdown", 1e9)) > constraints["max_drawdown"]:
        return False
    if "min_win_rate" in constraints and float(metrics.get("win_rate", 0)) < constraints["min_win_rate"]:
        return False
    return True


def rank_results(
    results: list[dict[str, Any]],
    *,
    objective: str,
    constraints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return constraint-passing results sorted best-first with result_rank set.

    NaN/Inf objective values sort last; ties break by config_hash ascending.
    """
    if objective not in OBJECTIVE_METRICS:
        raise ValueError(f"unsupported objective metric {objective!r}")
    direction = OBJECTIVE_METRICS[objective]
    constraints = constraints or {}

    kept = [r for r in results if _passes_constraints(r.get("metrics", {}), constraints)]

    def _sort_key(r: dict[str, Any]):
        val = _objective_value(r.get("metrics", {}), objective)
        # quarantined (None) always last regardless of direction
        is_valid = val is not None
        if val is None:
            ordered = 0.0
        else:
            ordered = -val if direction == "max" else val
        # (valid-first, ordered-objective, hash-tiebreak)
        return (0 if is_valid else 1, ordered, r.get("config_hash", ""))

    ranked = sorted(kept, key=_sort_key)
    for i, r in enumerate(ranked, start=1):
        r["result_rank"] = i
    return ranked


def compute_uplift(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    """Delta of candidate vs baseline on the headline metrics."""
    def _d(key: str) -> float:
        return float(candidate.get(key, 0.0)) - float(baseline.get(key, 0.0))

    return {
        "delta_total_return": _d("total_return"),
        "delta_sharpe": _d("sharpe"),
        "delta_max_drawdown": _d("max_drawdown"),  # negative = improvement
        "delta_expectancy": _d("expectancy"),
    }


def robustness_verdict(
    metrics: dict[str, Any],
    *,
    baseline_max_dd: float,
    min_trades: int,
    min_uplift_pct: float,
    uplift_pct: float,
) -> RobustnessVerdict:
    """Grade robust/moderate/fragile from named HARD/SOFT checks (FR-020)."""
    # HARD checks
    trade_count_ok = float(metrics.get("total_trades", 0)) >= min_trades
    dd_ok = float(metrics.get("max_drawdown", 1e9)) <= baseline_max_dd
    # SOFT checks
    not_single_dominated = float(metrics.get("top_trade_pnl_share", 0.0)) < 0.40
    uplift_above_noise = uplift_pct >= min_uplift_pct

    if not (trade_count_ok and dd_ok):
        return RobustnessVerdict.FRAGILE
    if not_single_dominated and uplift_above_noise:
        return RobustnessVerdict.ROBUST
    return RobustnessVerdict.MODERATE


def robustly_beats(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    objective: str,
    min_trades: int = 30,
    min_uplift_pct: float = 5.0,
) -> bool:
    """The full FR-018 bar: uplift >= min, >= min_trades, no DD regression,
    verdict != fragile."""
    # NaN/Inf candidate objective can never win.
    cand_finite = _objective_value(candidate, objective)
    if cand_finite is None:
        return False
    base_obj = float(baseline.get(objective, 0.0))
    cand_obj = cand_finite
    if base_obj == 0:
        uplift_pct = 100.0 if cand_obj > 0 else 0.0
    else:
        uplift_pct = (cand_obj - base_obj) / abs(base_obj) * 100.0
    if uplift_pct < min_uplift_pct:
        return False
    if float(candidate.get("total_trades", 0)) < min_trades:
        return False
    if float(candidate.get("max_drawdown", 1e9)) > float(baseline.get("max_drawdown", 1e9)):
        return False
    verdict = robustness_verdict(
        candidate,
        baseline_max_dd=float(baseline.get("max_drawdown", 1e9)),
        min_trades=min_trades,
        min_uplift_pct=min_uplift_pct,
        uplift_pct=uplift_pct,
    )
    return verdict != RobustnessVerdict.FRAGILE
