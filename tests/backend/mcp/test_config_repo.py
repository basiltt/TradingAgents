"""MCPConfigRepository tests — TASK-P0-02."""
from __future__ import annotations

import pytest

from backend.mcp.core.errors import MCPConflictError


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_returns_failsafe_singleton(mcp_pool):
    from backend.mcp.repositories.config_repo import MCPConfigRepository

    cfg = await MCPConfigRepository(mcp_pool).get()
    assert cfg.enabled is False
    assert cfg.capability_tier == "READ_ONLY"
    assert cfg.safe_mode_flags == {"read_only": True, "allow_real_trades": False, "allow_debug": False}
    assert cfg.row_version == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_optimistic_concurrency(mcp_pool):
    from backend.mcp.repositories.config_repo import MCPConfigRepository

    repo = MCPConfigRepository(mcp_pool)
    cfg = await repo.get()
    updated = await repo.update(
        {"enabled": True, "enabled_groups": ["scans"]},
        expected_row_version=cfg.row_version,
    )
    assert updated.enabled is True
    assert updated.enabled_groups == ["scans"]
    assert updated.row_version == cfg.row_version + 1

    # stale row_version -> conflict
    with pytest.raises(MCPConflictError):
        await repo.update({"enabled": False}, expected_row_version=cfg.row_version)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_set_token_hash_and_kill_epoch(mcp_pool):
    from backend.mcp.repositories.config_repo import MCPConfigRepository

    repo = MCPConfigRepository(mcp_pool)
    await repo.set_token_hash("abc123hash")
    cfg = await repo.get()
    assert cfg.access_token_hash == "abc123hash"

    # enable, then kill-switch forces OFF + bumps kill_epoch
    await repo.update({"enabled": True}, expected_row_version=cfg.row_version)
    new_kill = await repo.bump_kill_epoch()
    after = await repo.get()
    assert after.enabled is False
    assert after.kill_epoch == new_kill


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repair_to_failsafe_forces_off_on_corrupt_flags(mcp_pool):
    from backend.mcp.repositories.config_repo import MCPConfigRepository

    repo = MCPConfigRepository(mcp_pool)
    cfg = await repo.get()
    await repo.update({"enabled": True}, expected_row_version=cfg.row_version)
    # corrupt the flags directly
    async with mcp_pool.acquire() as conn:
        await conn.execute("UPDATE mcp_config SET safe_mode_flags='{}'::jsonb WHERE id=1")
    await repo.repair_to_failsafe()
    after = await repo.get()
    assert after.enabled is False
    assert after.safe_mode_flags["read_only"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_egress_consent_recorded_once(mcp_pool):
    """FR-033: enable records data-egress consent exactly once (idempotent)."""
    from backend.mcp.repositories.config_repo import MCPConfigRepository

    repo = MCPConfigRepository(mcp_pool)
    await repo.repair_to_failsafe()
    cfg0 = await repo.get()
    assert cfg0.egress_consent_at is None  # not consented yet

    ts1 = await repo.record_egress_consent()
    assert ts1 is not None
    cfg1 = await repo.get()
    assert cfg1.egress_consent_at == ts1

    # second call must NOT overwrite (COALESCE keeps the original)
    ts2 = await repo.record_egress_consent()
    assert ts2 == ts1
