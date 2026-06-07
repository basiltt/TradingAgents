"""Tests for enable preflight — TASK-P0-10 (AC-002)."""
from __future__ import annotations

import pytest


def _base_cfg(**over):
    from backend.mcp.repositories.config_repo import MCPConfig

    defaults = dict(
        enabled=False, bind_host="127.0.0.1", access_token_hash="a" * 64,
        capability_tier="READ_ONLY", enabled_groups=["scans"], enabled_tools={},
        safe_mode_flags={"read_only": True, "allow_real_trades": False, "allow_debug": False},
        row_version=0, config_epoch=0, kill_epoch=0, installation_id="x",
        audit_retention_days=365, sweep_retention_days=90,
    )
    defaults.update(over)
    return MCPConfig(**defaults)


def test_preflight_passes_with_valid_read_only_config():
    from backend.mcp.core.preflight import run_preflight

    result = run_preflight(_base_cfg(), schema_version=45, optimizer_enabled=False)
    assert result.ok, result.failed_invariant


def test_preflight_fails_without_token():
    from backend.mcp.core.preflight import run_preflight

    result = run_preflight(_base_cfg(access_token_hash=None), schema_version=45, optimizer_enabled=False)
    assert not result.ok
    assert "token" in result.failed_invariant.lower()


def test_preflight_fails_non_loopback_bind():
    from backend.mcp.core.preflight import run_preflight

    result = run_preflight(_base_cfg(bind_host="0.0.0.0"), schema_version=45, optimizer_enabled=False)
    assert not result.ok
    assert "loopback" in result.failed_invariant.lower() or "bind" in result.failed_invariant.lower()


def test_preflight_fails_wrong_migration_version():
    from backend.mcp.core.preflight import run_preflight

    result = run_preflight(_base_cfg(), schema_version=40, optimizer_enabled=False)
    assert not result.ok
    assert "migration" in result.failed_invariant.lower() or "version" in result.failed_invariant.lower()


def test_preflight_fails_not_read_only_safe_mode():
    from backend.mcp.core.preflight import run_preflight

    result = run_preflight(
        _base_cfg(safe_mode_flags={"read_only": False, "allow_real_trades": False, "allow_debug": False}),
        schema_version=45, optimizer_enabled=False,
    )
    assert not result.ok


def test_preflight_optimizer_invariants_only_when_optimizer_enabled():
    from backend.mcp.core.preflight import run_preflight

    # optimizer off -> shm/SLI invariants skipped -> passes
    r1 = run_preflight(_base_cfg(), schema_version=45, optimizer_enabled=False,
                       shm_free_ok=False, live_slis_present=False)
    assert r1.ok
    # optimizer on -> shm/SLI invariants enforced -> fails
    r2 = run_preflight(_base_cfg(capability_tier="BACKTEST"), schema_version=45,
                       optimizer_enabled=True, shm_free_ok=False, live_slis_present=True)
    assert not r2.ok
    assert "shm" in r2.failed_invariant.lower()
