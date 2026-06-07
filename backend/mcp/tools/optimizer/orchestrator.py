"""SweepOrchestrator — TASK-P4-05/06.

Coordinates a sweep: generate combos -> run each via the BacktestRunner ->
aggregate metrics -> rank (with constraints) -> compute baseline uplift ->
pick the robust winner (or "keep current"). `run_sweep_inproc` is the pure,
unit-testable core driven by an injected runner (FakeBacktestRunner in tests,
the real ProcessPool runner in production).
"""
from __future__ import annotations

from typing import Any, Optional

from backend.mcp.tools.optimizer.combos import config_hash, generate_combos
from backend.mcp.tools.optimizer.ranker import (
    _objective_value,
    compute_uplift,
    rank_results,
    robustly_beats,
    robustness_verdict,
)


def _finite_objective(result: dict[str, Any], objective: str) -> bool:
    """True if the result's objective metric is a finite (non-NaN/Inf) value."""
    return _objective_value(result.get("metrics", {}), objective) is not None


async def run_sweep_inproc(
    *,
    runner,
    space: dict[str, list[Any]],
    base: dict[str, Any],
    strategy: str,
    objective: str,
    signals: list[dict[str, Any]],
    snapshot: dict[str, Any],
    instrument_info: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    baseline_metrics: dict[str, Any] | None = None,
    n: int = 100,
    seed: int = 0,
    min_trades: int = 30,
    min_uplift_pct: float = 5.0,
) -> dict[str, Any]:
    """Run a full sweep in-process. Returns ranked results + the robust winner
    (or keep_current=True)."""
    combos = generate_combos(space, strategy=strategy, base=base, n=n, seed=seed)

    results: list[dict[str, Any]] = []
    for cfg in combos:
        metrics = await runner.run_one(cfg, signals, snapshot, instrument_info)
        results.append(
            {"config": cfg, "config_hash": config_hash(cfg), "metrics": metrics}
        )

    ranked = rank_results(results, objective=objective, constraints=constraints)

    winner: Optional[dict[str, Any]] = None
    keep_current = False
    if not ranked:
        # every combo was excluded by constraints -> nothing can beat current
        keep_current = True
    else:
        top = ranked[0]
        if baseline_metrics is not None:
            beats = robustly_beats(
                top["metrics"], baseline_metrics, objective=objective,
                min_trades=min_trades, min_uplift_pct=min_uplift_pct,
            )
            if beats:
                base_obj = float(baseline_metrics.get(objective, 0.0))
                cand_obj = float(top["metrics"].get(objective, 0.0))
                uplift_pct = (
                    100.0 if base_obj == 0 and cand_obj > 0
                    else (0.0 if base_obj == 0 else (cand_obj - base_obj) / abs(base_obj) * 100.0)
                )
                winner = {
                    **top,
                    "uplift": compute_uplift(top["metrics"], baseline_metrics),
                    "verdict": robustness_verdict(
                        top["metrics"],
                        baseline_max_dd=float(baseline_metrics.get("max_drawdown", 1e9)),
                        min_trades=min_trades, min_uplift_pct=min_uplift_pct,
                        uplift_pct=uplift_pct,
                    ).value,
                }
            else:
                keep_current = True
        else:
            # no baseline supplied -> top is the winner, unless its objective is
            # NaN/Inf (quarantined) in which case there is no valid winner.
            if _finite_objective(top, objective):
                winner = dict(top)

    return {
        "ranked": ranked,
        "winner": winner,
        "keep_current": keep_current,
        "total_combos": len(combos),
        "objective": objective,
        "fidelity_caveat": (
            "Backtest is a candle-resolution simulation (~1% deviation from live; "
            "in-sample only for MVP). Treat the projected edge as approximate."
        ),
    }
