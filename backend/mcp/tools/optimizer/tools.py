"""Optimizer MCP tools — TASK-P4-07.

sweep_estimate (pure pre-flight: combo count + feasibility) and optimize_config
(baseline + sweep + rank + proposal) exposed to the agent. The agent can only
PROPOSE; a human approves the winning config in the app UI.

MVP note: optimize_config runs the orchestrator in-process via the injected
BacktestRunner. The ProcessPool/shared-memory execution path is a performance
optimization layered on the same orchestrator core (which is already pure and
deterministic).
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError, MCPValidationError
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool
from backend.mcp.tools.optimizer.combos import (
    ComboGenerationError,
    _grid_count,
)
from backend.mcp.tools.optimizer.ranker import OBJECTIVE_METRICS


class SweepEstimateIn(BaseModel):
    space: dict[str, list[Any]] = Field(default_factory=dict)
    strategy: str = "grid"
    n: int = Field(default=100, ge=1, le=5000)


class SweepEstimateOut(BaseModel):
    combo_count: int
    feasible: bool
    reason: Optional[str] = None
    cap: int = 5000


@tool(
    name="sweep_estimate",
    group=ToolGroup.OPTIMIZER,
    input_schema=SweepEstimateIn,
    output_schema=SweepEstimateOut,
    safety_class=SafetyClass.BACKTEST,
)
async def sweep_estimate(args: SweepEstimateIn, ctx: Any) -> SweepEstimateOut:
    """Estimate a sweep's size + feasibility BEFORE running it (no execution)."""
    from backend.mcp.tools.optimizer.combos import MAX_SWEEP_COMBOS

    if not args.space or any(not v for v in args.space.values()):
        return SweepEstimateOut(combo_count=0, feasible=False, reason="empty search space")
    if args.strategy == "grid":
        count = _grid_count(args.space)
    else:
        count = min(args.n, _grid_count(args.space))
    feasible = count <= MAX_SWEEP_COMBOS
    reason = None if feasible else f"{count} combos exceeds cap {MAX_SWEEP_COMBOS}; narrow ranges or use random search"
    return SweepEstimateOut(combo_count=count, feasible=feasible, reason=reason, cap=MAX_SWEEP_COMBOS)


class OptimizeConfigIn(BaseModel):
    space: dict[str, list[Any]]
    objective: str = "sharpe"
    strategy: str = "grid"
    constraints: Optional[dict[str, Any]] = None
    base: Optional[dict[str, Any]] = None
    n: int = Field(default=100, ge=1, le=5000)
    seed: int = 0
    # Optional apply target: when BOTH are provided and a robust winner beats the
    # live config, the tool PERSISTS a pending proposal for human approval. With
    # them absent, the tool is analysis-only (returns the winner, stores nothing).
    target_schedule_id: Optional[str] = None
    target_config_index: Optional[int] = Field(default=None, ge=0)


class OptimizeConfigOut(BaseModel):
    winner: Optional[dict[str, Any]]
    keep_current: bool
    total_combos: int
    top_n: list[dict[str, Any]]
    fidelity_caveat: str
    objective: str
    # Set when a proposal was persisted for human approval (apply-target path).
    proposal_id: Optional[str] = None
    proposal_error: Optional[str] = None


@tool(
    name="optimize_config",
    group=ToolGroup.OPTIMIZER,
    input_schema=OptimizeConfigIn,
    output_schema=OptimizeConfigOut,
    safety_class=SafetyClass.BACKTEST,
    mutating=True,
)
async def optimize_config(args: OptimizeConfigIn, ctx: Any) -> OptimizeConfigOut:
    """Baseline + sweep + rank: find the best AutoTradeConfig and PROPOSE it.

    The agent cannot apply the result — a human approves it in the app UI.
    """
    if args.objective not in OBJECTIVE_METRICS:
        raise MCPValidationError(
            f"unsupported objective {args.objective!r}; choose from {sorted(OBJECTIVE_METRICS)}"
        )
    runner = getattr(ctx.services, "backtest_runner", None)
    if runner is None:
        raise MCPServiceUnavailableError("optimizer execution backend unavailable")

    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    # baseline = the current live config's metrics, if the runner can provide one
    baseline = getattr(ctx, "baseline_metrics", None)
    try:
        result = await run_sweep_inproc(
            runner=runner,
            space=args.space,
            base=args.base or {},
            strategy=args.strategy,
            objective=args.objective,
            constraints=args.constraints,
            signals=[],
            snapshot={},
            instrument_info={},
            baseline_metrics=baseline,
            n=args.n,
            seed=args.seed,
        )
    except ComboGenerationError as exc:
        raise MCPValidationError(str(exc)) from exc

    winner = result["winner"]
    proposal_id: Optional[str] = None
    proposal_error: Optional[str] = None

    # Apply-target path: when the agent targets a live schedule/config AND a
    # robust winner beat the baseline, PERSIST a pending proposal for human
    # approval. The agent never applies — it only enqueues for a human. Any
    # failure here is reported, not raised, so the analysis result still returns.
    if winner and args.target_schedule_id is not None and args.target_config_index is not None:
        db = getattr(ctx.services, "db", None)
        if db is None or getattr(db, "pool", None) is None:
            proposal_error = "proposal storage unavailable"
        else:
            try:
                from backend.mcp.repositories.proposal_repo import ProposalRepository
                from backend.mcp.tools.optimizer.proposal_service import (
                    ProposalApplyError,
                    create_proposal_from_winner,
                )

                repo = ProposalRepository(db.pool)
                proposal_id = await create_proposal_from_winner(
                    proposal_repo=repo,
                    prior_config=args.base or {},
                    winner_config=winner.get("config", {}),
                    target_schedule_id=args.target_schedule_id,
                    target_config_index=args.target_config_index,
                    risk_verdict={
                        "robustness": winner.get("verdict"),
                        "uplift": winner.get("uplift"),
                    },
                )
            except ProposalApplyError as exc:
                proposal_error = str(exc)

    return OptimizeConfigOut(
        winner=winner,
        keep_current=result["keep_current"],
        total_combos=result["total_combos"],
        top_n=result["ranked"][:20],
        fidelity_caveat=result["fidelity_caveat"],
        objective=result["objective"],
        proposal_id=proposal_id,
        proposal_error=proposal_error,
    )
