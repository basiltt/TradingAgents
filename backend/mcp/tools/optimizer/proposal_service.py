"""Proposal approval service — TASK-P4-10/11 (the human-apply money path).

Ties the tested apply policy (sanitize -> ceiling -> merged-validate) to the
proposal lifecycle + the atomic DB writer. Called ONLY from the control-plane
approve endpoint (human-authed), never from an agent tool.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from backend.mcp.repositories.proposal_repo import ProposalRepository
from backend.mcp.tools.optimizer.apply import (
    ApplyRejected,
    build_diff,
    sanitize_patch,
    validate_full_config,
    validate_merged_config,
)


class ProposalApplyError(Exception):
    """Raised when a proposal cannot be applied (expired, drift, invalid, etc.)."""


async def create_proposal_from_winner(
    *,
    proposal_repo: ProposalRepository,
    prior_config: dict[str, Any],
    winner_config: dict[str, Any],
    target_schedule_id: str,
    target_config_index: int,
    risk_verdict: Optional[dict[str, Any]] = None,
    sweep_id: Optional[str] = None,
) -> str:
    """Persist a sweep winner as a PENDING proposal for human approval.

    This is the create side of the money path — invoked from the optimizer tool
    when a robust winner beats the live config. It validates the proposed config
    through the SAME sanitize -> ceiling -> merged-validate gates that approval
    will re-run (fail fast: never store a proposal that could never be applied),
    and records a per-field diff plus the full prior config (drift baseline).

    The agent never reaches this with apply power: it only creates a pending row;
    a human must approve before anything touches live config.
    """
    # Reject up front if the proposed config can't clear the apply policy — no
    # point storing a proposal a human could only ever see rejected.
    sanitized = sanitize_patch(winner_config, reject_if_empty=True)
    validate_merged_config(prior_config, sanitized)

    diff = build_diff(prior_config, winner_config)
    if not diff["fields"]:
        raise ProposalApplyError("winner is identical to the live config; nothing to propose")

    # Store the full merged config (current ⊕ sanitized winner) so approval
    # applies exactly what was reviewed.
    merged = {**prior_config, **sanitized}
    return await proposal_repo.create(
        sweep_id=sweep_id,
        target_schedule_id=target_schedule_id,
        target_config_index=target_config_index,
        config=merged,
        diff=diff,
        risk_verdict=risk_verdict,
    )


async def approve_proposal(
    *,
    proposal_repo: ProposalRepository,
    db: Any,
    proposal_id: str,
    approver: str,
    clock_now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Approve + apply a pending proposal. Returns the applied summary or raises
    ProposalApplyError."""
    now = clock_now or datetime.now(timezone.utc)
    prop = await proposal_repo.get(proposal_id)
    if prop is None:
        raise ProposalApplyError(f"proposal {proposal_id!r} not found")
    if prop["status"] != "pending":
        raise ProposalApplyError(f"proposal is {prop['status']}, not pending")

    # expiry (virtual-clock friendly)
    expires_at = prop.get("expires_at")
    if expires_at:
        exp = datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now >= exp:
            await proposal_repo.transition(proposal_id, to_status="expired")
            raise ProposalApplyError("proposal has expired")

    target_schedule_id = prop.get("target_schedule_id")
    target_index = prop.get("target_config_index")
    if target_schedule_id is None or target_index is None:
        raise ProposalApplyError("proposal has no apply target (schedule/index)")

    # the prior config the proposal was computed against (drift baseline + revert)
    diff = prop.get("diff") or {}
    prior = diff.get("before")
    if prior is None:
        raise ProposalApplyError("proposal diff has no prior config for drift-guard/revert")

    patch = prop.get("config") or {}
    # sanitize -> ceiling -> merged-validate (raises ApplyRejected on failure)
    try:
        sanitize_patch(patch, reject_if_empty=True)
        merged = validate_merged_config(prior, patch)
    except ApplyRejected as exc:
        await proposal_repo.transition(proposal_id, to_status="rejected", approver=approver)
        raise ProposalApplyError(str(exc)) from exc

    # atomic read-merge-write under FOR UPDATE with the drift-guard
    try:
        applied_prior = await db.apply_auto_trade_config_atomic(
            target_schedule_id, target_index, merged, expected_prior=prior,
        )
    except ValueError as exc:
        raise ProposalApplyError(str(exc)) from exc

    version = now.isoformat()
    await proposal_repo.transition(
        proposal_id, to_status="applied", approver=approver, applied_config_version=version,
    )
    return {
        "proposal_id": proposal_id,
        "applied_config_version": version,
        "target_schedule_id": target_schedule_id,
        "prior_config": applied_prior,
    }


async def revert_proposal(
    *,
    proposal_repo: ProposalRepository,
    db: Any,
    proposal_id: str,
    approver: str,
) -> dict[str, Any]:
    """Restore the prior config of an applied proposal THROUGH the same policy
    pipeline (sanitize -> ceiling -> validate), then mark reverted."""
    prop = await proposal_repo.get(proposal_id)
    if prop is None:
        raise ProposalApplyError(f"proposal {proposal_id!r} not found")
    if prop["status"] != "applied":
        raise ProposalApplyError(f"proposal is {prop['status']}, not applied")
    diff = prop.get("diff") or {}
    prior = diff.get("before")
    if prior is None:
        raise ProposalApplyError("no prior config to revert to")

    target_schedule_id = prop.get("target_schedule_id")
    target_index = prop.get("target_config_index")
    # revert = write the prior config back. It must clear the SAME absolute
    # sanity ceiling as a forward apply — a stored prior that exceeds the hard
    # leverage/capital bounds (or has NaN / no stop loss) must never be restored.
    try:
        validate_full_config(prior)
    except ApplyRejected as exc:
        raise ProposalApplyError(f"prior config fails the safety ceiling: {exc}") from exc

    try:
        await db.apply_auto_trade_config_atomic(
            target_schedule_id, target_index, prior, expected_prior=None,
        )
    except ValueError as exc:
        raise ProposalApplyError(str(exc)) from exc
    await proposal_repo.transition(proposal_id, to_status="reverted", approver=approver)
    return {"proposal_id": proposal_id, "reverted": True}
