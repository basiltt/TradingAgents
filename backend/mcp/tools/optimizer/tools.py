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


def _validate_scan_source(scan_source: Optional[dict[str, Any]]) -> None:
    """Reject a malformed scan_source so the sweep doesn't silently run on empty
    signals (→ a misleading 'keep_current'). Empty/None is allowed (date-range
    default). 'schedule' mode requires schedule_id; 'explicit' requires scan_ids."""
    if not scan_source:
        return
    if not isinstance(scan_source, dict):
        raise MCPValidationError("scan_source must be an object")
    mode = scan_source.get("mode")
    if mode in (None, "date_range"):
        return
    if mode == "schedule" and not scan_source.get("schedule_id"):
        raise MCPValidationError("scan_source mode 'schedule' requires a schedule_id")
    if mode == "explicit" and not scan_source.get("scan_ids"):
        raise MCPValidationError("scan_source mode 'explicit' requires scan_ids")
    if mode not in ("date_range", "schedule", "explicit"):
        raise MCPValidationError(f"unknown scan_source mode {mode!r}")


async def _live_target_config(db: Any, schedule_id: str, config_index: int) -> Optional[dict[str, Any]]:
    """Read the REAL live auto-trade config at (schedule_id, config_index) to use
    as a proposal's drift baseline — never trust the agent-supplied `base`."""
    import json

    try:
        row = await db.get_scheduled_scan(schedule_id)
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    scan_config = row.get("scan_config") or {}
    # asyncpg may return jsonb as a raw string when no codec is registered.
    if isinstance(scan_config, str):
        try:
            scan_config = json.loads(scan_config)
        except (ValueError, TypeError):
            return None
    if not isinstance(scan_config, dict):
        return None
    configs = scan_config.get("auto_trade_configs") or []
    if not (0 <= config_index < len(configs)):
        return None
    cfg = configs[config_index]
    return dict(cfg) if isinstance(cfg, dict) else None


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
    # Real-data execution window: when provided, the optimizer loads the historical
    # signals + klines for this range ONCE and replays every combo against that
    # in-sample snapshot via the real BacktestEngine. Absent → caller must inject a
    # runner with its own data (test path).
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    scan_source: Optional[dict[str, Any]] = None
    starting_capital: float = Field(default=1000.0, gt=0)
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

    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc, run_sweep_pooled
    from backend.mcp.tools.optimizer.runner_pool import supports_process_pool

    # Load the historical signals + klines + instrument params ONCE for the
    # window, then replay every combo against that in-sample snapshot. When a
    # date range is given and the runner can load inputs (the real
    # BacktestService), use real data; otherwise fall back to empty inputs (the
    # injected-runner test path provides its own).
    signals: list[Any] = []
    snapshot: dict[str, Any] = {}
    instrument_info: dict[str, Any] = {}
    base_cfg = dict(args.base or {})
    _validate_scan_source(args.scan_source)

    # When an apply-target is given, the sweep + uplift baseline MUST run against
    # the REAL live config (not agent-supplied `base`). Otherwise the agent could
    # send a weak `base` so the winner "beats" a strawman, and the human would
    # approve metrics whose backtest used different non-swept fields than live.
    # The sweep overlays swept dims onto this live base, so the winner's
    # non-swept fields == live's, exactly what approval applies.
    target_live_config: Optional[dict[str, Any]] = None
    if args.target_schedule_id is not None and args.target_config_index is not None:
        db_h = getattr(ctx.services, "db", None)
        if db_h is not None and getattr(db_h, "pool", None) is not None:
            target_live_config = await _live_target_config(
                db_h, args.target_schedule_id, args.target_config_index
            )
            if target_live_config is not None:
                # live config is the authoritative base; agent `base` only
                # contributes fields the live config doesn't define.
                base_cfg = {**base_cfg, **target_live_config}

    if args.date_range_start and args.date_range_end and hasattr(runner, "load_inputs"):
        load_cfg = {
            **base_cfg,
            "date_range_start": args.date_range_start,
            "date_range_end": args.date_range_end,
            "scan_source": args.scan_source or {},
            "starting_capital": args.starting_capital,
        }
        try:
            signals, snapshot, instrument_info = await runner.load_inputs(load_cfg)
        except Exception as exc:  # noqa: BLE001 — surface as a clean validation error
            raise MCPServiceUnavailableError(f"could not load backtest inputs: {exc}") from exc
        base_cfg.setdefault("starting_capital", args.starting_capital)

    # Real baseline: run the current/base config through the SAME harness so
    # uplift is measured against an actual backtest, not a ctx stub.
    baseline = getattr(ctx, "baseline_metrics", None)
    if baseline is None and (signals or snapshot):
        try:
            baseline = await runner.run_one(base_cfg, signals, snapshot, instrument_info, deadline=None)
        except Exception:  # noqa: BLE001 — no baseline → uplift falls back to absolute
            baseline = None

    # Live-protection gate: the synchronous optimize_config runs a full grid of
    # real backtests, so it must yield to the live-SLI breaker exactly like the
    # async sweep_run path — otherwise it could starve order placement.
    manager = getattr(getattr(ctx.services, "_state", None), "mcp_manager", None)
    if manager is not None and getattr(manager, "mcp_permitted", None) is not None:
        from backend.mcp.tools.optimizer.sweep_tools import _await_breaker_clear

        await _await_breaker_clear(manager)

    try:
        # Offload combo CPU work to a spawn ProcessPool when supported (POSIX) so
        # the live event loop is never starved (FR-036). On Windows / no-pool,
        # fall back to the in-process path — same pure engine. The pooled path
        # needs a real (picklable) runner's engine, which lives in runner_pool;
        # when the caller injected a non-real runner (tests), stay in-process.
        use_pool = (
            supports_process_pool()
            and bool(signals or snapshot)
            and hasattr(runner, "load_inputs")  # the real BacktestService
        )
        if use_pool:
            result = await run_sweep_pooled(
                space=args.space,
                base=base_cfg,
                strategy=args.strategy,
                objective=args.objective,
                constraints=args.constraints,
                signals=signals,
                snapshot=snapshot,
                instrument_info=instrument_info,
                baseline_metrics=baseline,
                n=args.n,
                seed=args.seed,
            )
        else:
            result = await run_sweep_inproc(
                runner=runner,
                space=args.space,
                base=base_cfg,
                strategy=args.strategy,
                objective=args.objective,
                constraints=args.constraints,
                signals=signals,
                snapshot=snapshot,
                instrument_info=instrument_info,
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

                # Use the SAME live config the sweep ran against (fetched above)
                # as the proposal baseline + drift baseline, so the diff the human
                # reviews is exactly current-live → swept-winner. Re-fetch only if
                # it wasn't captured (shouldn't happen on the target path).
                prior_for_target = target_live_config
                if prior_for_target is None:
                    prior_for_target = await _live_target_config(
                        db, args.target_schedule_id, args.target_config_index
                    )
                if prior_for_target is None:
                    raise ProposalApplyError(
                        "target schedule/config not found for proposal baseline"
                    )

                repo = ProposalRepository(db.pool)
                proposal_id = await create_proposal_from_winner(
                    proposal_repo=repo,
                    prior_config=prior_for_target,
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
