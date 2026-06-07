"""Apply-loop end-to-end tests — TASK-P4-08/10/11 (the money path, real DB)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest


async def _seed_schedule(pool, configs):
    """Insert a scheduled_scans row with an auto_trade_configs list."""
    sid = "sched-" + uuid.uuid4().hex[:8]
    scan_config = {"auto_trade_configs": configs}
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO scheduled_scans (id, name, schedule_type, schedule_config, "
            "scan_config, status, created_at, updated_at) "
            "VALUES ($1,$2,'interval',$3::jsonb,$4::jsonb,'active',now(),now())",
            sid, "test", json.dumps({"interval_minutes": 60}), json.dumps(scan_config),
        )
    return sid


def _base_config(**over):
    cfg = {
        "account_id": "acc1", "leverage": 10, "stop_loss_pct": 100.0,
        "take_profit_pct": 150.0, "capital_pct": 5.0, "direction": "straight",
    }
    cfg.update(over)
    return cfg


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_applies_config_to_live_scan(mcp_pool):
    from backend.mcp.repositories.proposal_repo import ProposalRepository
    from backend.mcp.tools.optimizer.proposal_service import approve_proposal

    prior = _base_config(take_profit_pct=150.0)
    sid = await _seed_schedule(mcp_pool, [prior])

    repo = ProposalRepository(mcp_pool)
    pid = await repo.create(
        sweep_id=None, target_schedule_id=sid, target_config_index=0,
        config={"take_profit_pct": 250.0},  # the swept improvement
        diff={"before": prior},
    )

    summary = await approve_proposal(proposal_repo=repo, db=_RealDB(mcp_pool),
                                     proposal_id=pid, approver="op")
    assert summary["applied_config_version"]

    # the live scan now has the merged config
    async with mcp_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scan_config FROM scheduled_scans WHERE id=$1", sid)
    sc = row["scan_config"] if isinstance(row["scan_config"], dict) else json.loads(row["scan_config"])
    assert sc["auto_trade_configs"][0]["take_profit_pct"] == 250.0
    assert sc["auto_trade_configs"][0]["leverage"] == 10  # unchanged preserved

    # proposal is now applied
    prop = await repo.get(pid)
    assert prop["status"] == "applied"


class _RealDB:
    """Minimal AsyncAnalysisDB-like wrapper exposing the atomic apply method
    bound to a test pool."""

    def __init__(self, pool):
        self.pool = pool

    async def apply_auto_trade_config_atomic(self, schedule_id, config_index, merged_config, *, expected_prior=None):
        from backend.async_persistence import AsyncAnalysisDB

        # call the real implementation with self as a stand-in (it only uses self.pool)
        return await AsyncAnalysisDB.apply_auto_trade_config_atomic(
            self, schedule_id, config_index, merged_config, expected_prior=expected_prior
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_rejects_dangerous_field_and_leaves_config_unchanged(mcp_pool):
    from backend.mcp.repositories.proposal_repo import ProposalRepository
    from backend.mcp.tools.optimizer.proposal_service import (
        ProposalApplyError,
        approve_proposal,
    )

    prior = _base_config()
    sid = await _seed_schedule(mcp_pool, [prior])
    repo = ProposalRepository(mcp_pool)
    # a proposal whose patch is ENTIRELY non-sweepable (live-enabling) fields
    pid = await repo.create(
        sweep_id=None, target_schedule_id=sid, target_config_index=0,
        config={"allow_real_trades": True, "ai_manager_enabled": True},
        diff={"before": prior},
    )
    with pytest.raises(ProposalApplyError):
        await approve_proposal(proposal_repo=repo, db=_RealDB(mcp_pool), proposal_id=pid, approver="op")

    # live config unchanged + proposal rejected
    async with mcp_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scan_config FROM scheduled_scans WHERE id=$1", sid)
    sc = row["scan_config"] if isinstance(row["scan_config"], dict) else json.loads(row["scan_config"])
    assert "allow_real_trades" not in sc["auto_trade_configs"][0]
    assert (await repo.get(pid))["status"] == "rejected"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_rejects_expired_proposal(mcp_pool):
    from backend.mcp.repositories.proposal_repo import ProposalRepository
    from backend.mcp.tools.optimizer.proposal_service import (
        ProposalApplyError,
        approve_proposal,
    )

    prior = _base_config()
    sid = await _seed_schedule(mcp_pool, [prior])
    repo = ProposalRepository(mcp_pool)
    # create with a TTL in the past (clock_now far before -> expires before now)
    past = datetime.now(timezone.utc) - timedelta(hours=48)
    pid = await repo.create(
        sweep_id=None, target_schedule_id=sid, target_config_index=0,
        config={"take_profit_pct": 200.0}, diff={"before": prior},
        ttl_hours=1, clock_now=past,
    )
    with pytest.raises(ProposalApplyError):
        await approve_proposal(proposal_repo=repo, db=_RealDB(mcp_pool), proposal_id=pid, approver="op")
    assert (await repo.get(pid))["status"] == "expired"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_drift_guard_rejects_when_target_changed(mcp_pool):
    from backend.mcp.repositories.proposal_repo import ProposalRepository
    from backend.mcp.tools.optimizer.proposal_service import (
        ProposalApplyError,
        approve_proposal,
    )

    prior = _base_config(take_profit_pct=150.0)
    sid = await _seed_schedule(mcp_pool, [prior])
    repo = ProposalRepository(mcp_pool)
    pid = await repo.create(
        sweep_id=None, target_schedule_id=sid, target_config_index=0,
        config={"take_profit_pct": 250.0}, diff={"before": prior},
    )
    # someone edits the live config AFTER the proposal was made (drift)
    async with mcp_pool.acquire() as conn:
        drifted = _base_config(take_profit_pct=175.0)
        await conn.execute(
            "UPDATE scheduled_scans SET scan_config=$1::jsonb WHERE id=$2",
            json.dumps({"auto_trade_configs": [drifted]}), sid,
        )
    with pytest.raises(ProposalApplyError):
        await approve_proposal(proposal_repo=repo, db=_RealDB(mcp_pool), proposal_id=pid, approver="op")
