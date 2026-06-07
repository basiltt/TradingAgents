"""Async sweep tools — G1 (FR-021/040): fire-and-poll over a persisted sweep.

sweep_run launches the sweep in a background task and returns a sweep_id
immediately; the agent can disconnect and a later session polls sweep_status /
sweep_results (re-rankable by an alternate objective) or sweep_cancel. Results
persist in mcp_sweep_* via SweepRepository, so a crash leaves a resumable sweep.

optimize_config remains the synchronous one-shot convenience; these tools are the
long-running path.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError, MCPValidationError
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool
from backend.mcp.tools.optimizer.combos import (
    ComboGenerationError,
    MAX_SWEEP_COMBOS,
    _grid_count,
    config_hash,
    generate_combos,
)
from backend.mcp.tools.optimizer.ranker import (
    OBJECTIVE_METRICS,
    _objective_value,
    rank_results,
)


class SweepRunIn(BaseModel):
    space: dict[str, list[Any]]
    objective: str = "sharpe"
    strategy: str = "grid"
    constraints: Optional[dict[str, Any]] = None
    base: Optional[dict[str, Any]] = None
    n: int = Field(default=100, ge=1, le=5000)
    seed: int = 0
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    scan_source: Optional[dict[str, Any]] = None
    starting_capital: float = Field(default=1000.0, gt=0)


class SweepRunOut(BaseModel):
    sweep_id: str
    total_combos: int
    status: str


async def _execute_sweep(
    *, sweep_id: str, repo: Any, runner: Any, args: SweepRunIn,
    signals: list[Any], snapshot: dict[str, Any], instrument_info: dict[str, Any],
    manager: Any = None,
) -> None:
    """Background sweep body: run each combo, persist per-combo, finish the job.
    Resumable — skips config hashes already stored (crash recovery). Yields to
    the live-trading breaker: when SLIs degrade (manager.mcp_permitted() False)
    it pauses rather than competing with order placement (FR-037/NFR-002)."""
    try:
        combos = generate_combos(
            args.space, strategy=args.strategy, base=args.base or {}, n=args.n, seed=args.seed
        )
        done = await repo.completed_config_hashes(sweep_id)
        results: list[dict[str, Any]] = []
        for cfg in combos:
            h = config_hash(cfg)
            if h in done:
                continue
            # Live-protection gate: if the breaker is OPEN (trading SLIs degraded),
            # back off before doing more CPU/DB work. Bounded so a stuck breaker
            # can't hang the sweep forever — it ends as 'failed' via the timeout.
            await _await_breaker_clear(manager)
            import time as _t
            deadline = _t.monotonic() + 120.0  # per-combo timeout (runaway guard)
            metrics = await runner.run_one(cfg, signals, snapshot, instrument_info, deadline=deadline)
            obj = _objective_value(metrics, args.objective)
            await repo.write_result(
                sweep_id=sweep_id, config=cfg, config_hash=h, metrics=metrics,
                objective_value=obj,
            )
            results.append({"config": cfg, "config_hash": h, "metrics": metrics})
        # rank to stamp result_rank + pick best
        ranked = rank_results(results, objective=args.objective, constraints=args.constraints)
        for rank, r in enumerate(ranked, start=1):
            await repo.write_result(
                sweep_id=sweep_id, config=r["config"], config_hash=r["config_hash"],
                metrics=r["metrics"], objective_value=_objective_value(r["metrics"], args.objective),
                result_rank=rank,
            )
        await repo.finish_job(sweep_id, status="completed")
    except asyncio.CancelledError:
        # Shield the status write from the cancellation so the job is reliably
        # marked 'cancelled' (not left 'running'); recover_interrupted is the
        # backstop if even this is interrupted by loop teardown.
        try:
            await asyncio.shield(repo.finish_job(sweep_id, status="cancelled"))
        except Exception:  # noqa: BLE001
            pass
        raise
    except Exception:  # noqa: BLE001 — record failure, never crash the loop
        await repo.finish_job(sweep_id, status="failed")


async def _await_breaker_clear(manager: Any, *, max_wait_s: float = 60.0) -> None:
    """Block (bounded) while the live-SLI breaker is OPEN. Raises TimeoutError if
    it stays open past max_wait_s so the sweep ends rather than hanging."""
    if manager is None or getattr(manager, "mcp_permitted", None) is None:
        return
    waited = 0.0
    while not manager.mcp_permitted():
        if waited >= max_wait_s:
            raise TimeoutError("live-SLI breaker stayed open; sweep shed")
        await asyncio.sleep(1.0)
        waited += 1.0


@tool(
    name="sweep_run",
    group=ToolGroup.OPTIMIZER,
    input_schema=SweepRunIn,
    output_schema=SweepRunOut,
    safety_class=SafetyClass.BACKTEST,
    mutating=True,
)
async def sweep_run(args: SweepRunIn, ctx: Any) -> SweepRunOut:
    """Launch a parameter sweep in the background and return a sweep_id to poll. The agent can disconnect; results persist and are re-rankable later."""
    if args.objective not in OBJECTIVE_METRICS:
        raise MCPValidationError(
            f"unsupported objective {args.objective!r}; choose from {sorted(OBJECTIVE_METRICS)}"
        )
    count = _grid_count(args.space) if args.strategy == "grid" else min(args.n, _grid_count(args.space))
    if count > MAX_SWEEP_COMBOS:
        raise MCPValidationError(
            f"{count} combos exceeds cap {MAX_SWEEP_COMBOS}; narrow ranges or use random search"
        )
    repo = getattr(ctx.services, "sweep_repo", None)
    runner = getattr(ctx.services, "backtest_runner", None)
    if repo is None or runner is None:
        raise MCPServiceUnavailableError("sweep persistence/execution backend unavailable")

    # load real inputs once if a window is given
    signals: list[Any] = []
    snapshot: dict[str, Any] = {}
    instrument_info: dict[str, Any] = {}
    base_cfg = dict(args.base or {})
    if args.date_range_start and args.date_range_end and hasattr(runner, "load_inputs"):
        try:
            signals, snapshot, instrument_info = await runner.load_inputs({
                **base_cfg, "date_range_start": args.date_range_start,
                "date_range_end": args.date_range_end, "scan_source": args.scan_source or {},
                "starting_capital": args.starting_capital,
            })
        except Exception as exc:  # noqa: BLE001
            raise MCPServiceUnavailableError(f"could not load backtest inputs: {exc}") from exc

    try:
        combos = generate_combos(
            args.space, strategy=args.strategy, base=base_cfg, n=args.n, seed=args.seed
        )
    except ComboGenerationError as exc:
        raise MCPValidationError(str(exc)) from exc

    sweep_id = await repo.create_job(
        strategy=args.strategy, param_space=args.space, objective_metric=args.objective,
        total_combos=len(combos), principal_token_id=ctx.principal, session_id=ctx.session_id,
    )

    # fire-and-forget background task tracked on app.state for lifecycle/cancel.
    # The manager handle lets the sweep yield to the live-SLI breaker.
    state = getattr(ctx.services, "_state", None)
    manager = getattr(state, "mcp_manager", None) if state is not None else None
    task = asyncio.create_task(
        _execute_sweep(
            sweep_id=sweep_id, repo=repo, runner=runner, args=args,
            signals=signals, snapshot=snapshot, instrument_info=instrument_info,
            manager=manager,
        )
    )
    if state is not None:
        registry = getattr(state, "mcp_sweep_tasks", None)
        if registry is None:
            registry = {}
            state.mcp_sweep_tasks = registry
        registry[sweep_id] = task
        task.add_done_callback(lambda _t, sid=sweep_id: registry.pop(sid, None))

    return SweepRunOut(sweep_id=sweep_id, total_combos=len(combos), status="running")


class SweepStatusIn(BaseModel):
    sweep_id: str = Field(min_length=1, max_length=64)


class SweepStatusOut(BaseModel):
    sweep_id: str
    status: str
    total_combos: int
    completed_combos: int
    best_result_id: Optional[str] = None


@tool(
    name="sweep_status",
    group=ToolGroup.OPTIMIZER,
    input_schema=SweepStatusIn,
    output_schema=SweepStatusOut,
    safety_class=SafetyClass.BACKTEST,
)
async def sweep_status(args: SweepStatusIn, ctx: Any) -> SweepStatusOut:
    """Poll a sweep's progress (status + completed/total combos) by sweep_id."""
    repo = getattr(ctx.services, "sweep_repo", None)
    if repo is None:
        raise MCPServiceUnavailableError("sweep persistence unavailable")
    job = await repo.get_job(args.sweep_id)
    if job is None:
        raise MCPValidationError(f"unknown sweep_id {args.sweep_id!r}")
    return SweepStatusOut(
        sweep_id=args.sweep_id, status=job["status"],
        total_combos=job["total_combos"], completed_combos=job["completed_combos"],
        best_result_id=job.get("best_result_id"),
    )


class SweepResultsIn(BaseModel):
    sweep_id: str = Field(min_length=1, max_length=64)
    objective: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class SweepResultsOut(BaseModel):
    sweep_id: str
    results: list[dict[str, Any]]
    count: int
    reranked_by: Optional[str] = None


@tool(
    name="sweep_results",
    group=ToolGroup.OPTIMIZER,
    input_schema=SweepResultsIn,
    output_schema=SweepResultsOut,
    safety_class=SafetyClass.BACKTEST,
)
async def sweep_results(args: SweepResultsIn, ctx: Any) -> SweepResultsOut:
    """Get a sweep's stored results, optionally RE-RANKED by an alternate objective metric server-side (no re-run)."""
    repo = getattr(ctx.services, "sweep_repo", None)
    if repo is None:
        raise MCPServiceUnavailableError("sweep persistence unavailable")
    if args.objective is not None and args.objective not in OBJECTIVE_METRICS:
        raise MCPValidationError(f"unsupported objective {args.objective!r}")
    rows = await repo.results(args.sweep_id, objective=args.objective, limit=args.limit)
    return SweepResultsOut(
        sweep_id=args.sweep_id, results=rows, count=len(rows), reranked_by=args.objective
    )


class SweepCancelIn(BaseModel):
    sweep_id: str = Field(min_length=1, max_length=64)


class SweepCancelOut(BaseModel):
    sweep_id: str
    cancelled: bool


@tool(
    name="sweep_cancel",
    group=ToolGroup.OPTIMIZER,
    input_schema=SweepCancelIn,
    output_schema=SweepCancelOut,
    safety_class=SafetyClass.BACKTEST,
    mutating=True,
)
async def sweep_cancel(args: SweepCancelIn, ctx: Any) -> SweepCancelOut:
    """Cancel a running sweep; partial results are kept and remain queryable."""
    repo = getattr(ctx.services, "sweep_repo", None)
    if repo is None:
        raise MCPServiceUnavailableError("sweep persistence unavailable")
    # cancel the background task if present, then mark the job
    state = getattr(ctx.services, "_state", None)
    registry = getattr(state, "mcp_sweep_tasks", None) if state is not None else None
    if registry and args.sweep_id in registry:
        registry[args.sweep_id].cancel()
    cancelled = await repo.cancel_job(args.sweep_id)
    return SweepCancelOut(sweep_id=args.sweep_id, cancelled=cancelled)
