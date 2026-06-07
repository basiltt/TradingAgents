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
    per_combo_timeout_s: float | None = 120.0,
) -> dict[str, Any]:
    """Run a full sweep in-process. Returns ranked results + the robust winner
    (or keep_current=True). `per_combo_timeout_s` bounds each combo so one
    pathological config cannot hang the sweep (passed as run_one's deadline)."""
    import time

    combos = generate_combos(space, strategy=strategy, base=base, n=n, seed=seed)

    results: list[dict[str, Any]] = []
    for cfg in combos:
        deadline = (time.monotonic() + per_combo_timeout_s) if per_combo_timeout_s else None
        metrics = await runner.run_one(cfg, signals, snapshot, instrument_info, deadline=deadline)
        results.append(
            {"config": cfg, "config_hash": config_hash(cfg), "metrics": metrics}
        )

    return _rank_and_crown(
        results, total_combos=len(combos), objective=objective,
        constraints=constraints, baseline_metrics=baseline_metrics,
        min_trades=min_trades, min_uplift_pct=min_uplift_pct,
    )


def _rank_and_crown(
    results: list[dict[str, Any]],
    *,
    total_combos: int,
    objective: str,
    constraints: dict[str, Any] | None,
    baseline_metrics: dict[str, Any] | None,
    min_trades: int,
    min_uplift_pct: float,
) -> dict[str, Any]:
    """Shared rank + winner-crown tail used by the in-process AND pooled paths
    (identical ranking/robustness semantics regardless of how combos executed)."""
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
        "total_combos": total_combos,
        "objective": objective,
        "fidelity_caveat": (
            "Backtest is a candle-resolution simulation (~1% deviation from live; "
            "in-sample only for MVP). Treat the projected edge as approximate."
        ),
    }


async def run_sweep_pooled(
    *,
    space: dict[str, list[Any]],
    base: dict[str, Any],
    strategy: str,
    objective: str,
    signals: list[dict[str, Any]],
    snapshot: dict[str, list[dict[str, Any]]],
    instrument_info: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    baseline_metrics: dict[str, Any] | None = None,
    n: int = 100,
    seed: int = 0,
    min_trades: int = 30,
    min_uplift_pct: float = 5.0,
    max_workers: int | None = None,
    per_combo_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Run a sweep with combo CPU work offloaded to a spawn ProcessPool so the
    live event loop is never CPU-starved (FR-036). The PARENT collects each
    worker's metrics (workers are DB-less). `per_combo_timeout_s` bounds each
    worker via the engine's deadline AND a parent-side wait_for so one
    pathological config can neither hang the gather nor leak unbounded compute.
    """
    import asyncio
    import time

    from backend.mcp.tools.optimizer.runner_pool import _run_combo, make_sweep_pool

    combos = generate_combos(space, strategy=strategy, base=base, n=n, seed=seed)
    loop = asyncio.get_running_loop()
    pool = make_sweep_pool(max_workers=max_workers)
    results: list[dict[str, Any]] = []
    try:
        async def _one(cfg):
            deadline = time.monotonic() + per_combo_timeout_s
            fut = loop.run_in_executor(pool, _run_combo, cfg, signals, snapshot, instrument_info, deadline)
            try:
                # Parent-side guard: a little beyond the worker deadline so the
                # worker's own engine-cancel fires first; if the process is truly
                # wedged, wait_for stops US blocking (the worker is shed on pool
                # shutdown / cancel_futures).
                return await asyncio.wait_for(fut, timeout=per_combo_timeout_s + 15.0)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                return {}

        metrics_list = await asyncio.gather(*[_one(c) for c in combos], return_exceptions=True)
        for cfg, metrics in zip(combos, metrics_list):
            m = metrics if isinstance(metrics, dict) else {}
            results.append({"config": cfg, "config_hash": config_hash(cfg), "metrics": m})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return _rank_and_crown(
        results, total_combos=len(combos), objective=objective,
        constraints=constraints, baseline_metrics=baseline_metrics,
        min_trades=min_trades, min_uplift_pct=min_uplift_pct,
    )
