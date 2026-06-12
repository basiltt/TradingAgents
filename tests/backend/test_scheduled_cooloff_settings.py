"""Cool Off Time — Phase 4 scheduled config-save settings writer (FR-013 writer-1).

Unit-tests ScanSchedulerService._persist_cooloff_settings: per-account upsert of cool-off
settings from a saved scan_config, all-OFF disable propagation (DS14 last-write-wins), and
fail-open.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.scan_scheduler_service import ScanSchedulerService


def _svc_with_repo():
    svc = ScanSchedulerService.__new__(ScanSchedulerService)
    svc._db = MagicMock()
    repo = MagicMock()
    repo.upsert_settings = AsyncMock()
    svc._cooloff_repo = repo
    return svc, repo


@pytest.mark.asyncio
async def test_persist_upserts_enabled_account():
    svc, repo = _svc_with_repo()
    scan_config = {"auto_trade_configs": [
        {"account_id": "a", "cooloff_on_failure_enabled": True, "cooloff_on_failure_minutes": 60},
    ]}
    await svc._persist_cooloff_settings(scan_config)
    repo.upsert_settings.assert_awaited_once()
    acc, settings = repo.upsert_settings.await_args.args
    assert acc == "a"
    assert settings["failure_enabled"] is True
    assert settings["failure_minutes"] == 60


@pytest.mark.asyncio
async def test_persist_all_off_propagates_disable():
    # A scheduled save with every tier OFF is an explicit disable and MUST persist
    # (column-scoped upsert leaves any ACTIVE cool-off + streak untouched) so the user
    # can turn the feature off — the old all-OFF clobber guard (DS19) is superseded by
    # last-write-wins (DS14). Disabling via the durable scheduled surface is the toggle.
    svc, repo = _svc_with_repo()
    scan_config = {"auto_trade_configs": [{"account_id": "a"}]}  # no tier enabled
    await svc._persist_cooloff_settings(scan_config)
    repo.upsert_settings.assert_awaited_once()
    acc, settings = repo.upsert_settings.await_args.args
    assert acc == "a"
    assert settings["success_enabled"] is False
    assert settings["failure_enabled"] is False
    assert settings["double_success_enabled"] is False
    assert settings["double_failure_enabled"] is False


@pytest.mark.asyncio
async def test_persist_multiple_accounts():
    svc, repo = _svc_with_repo()
    scan_config = {"auto_trade_configs": [
        {"account_id": "a", "cooloff_on_success_enabled": True, "cooloff_on_success_minutes": 30},
        {"account_id": "b", "cooloff_on_double_failure_enabled": True, "cooloff_on_double_failure_minutes": 120},
        {"account_id": "c"},  # all-OFF -> still persisted (explicit disable for account c)
    ]}
    await svc._persist_cooloff_settings(scan_config)
    assert repo.upsert_settings.await_count == 3


@pytest.mark.asyncio
async def test_persist_no_configs_noop():
    svc, repo = _svc_with_repo()
    await svc._persist_cooloff_settings({})
    repo.upsert_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_fail_open_on_repo_error():
    svc, repo = _svc_with_repo()
    repo.upsert_settings = AsyncMock(side_effect=RuntimeError("db down"))
    scan_config = {"auto_trade_configs": [
        {"account_id": "a", "cooloff_on_failure_enabled": True, "cooloff_on_failure_minutes": 60},
    ]}
    # must not raise (a settings-save side-effect must never break schedule save)
    await svc._persist_cooloff_settings(scan_config)


@pytest.mark.asyncio
async def test_persist_no_repo_noop():
    svc = ScanSchedulerService.__new__(ScanSchedulerService)
    svc._db = None
    svc._cooloff_repo = None
    # no repo and no db -> no-op, no error
    await svc._persist_cooloff_settings({"auto_trade_configs": [{"account_id": "a"}]})


# ── MCP exposure (FR-030 / P4-2): cool-off fields pass strip_secret_keys ──────

def test_mcp_strip_secret_keys_preserves_cooloff_fields():
    """The 8 cool-off fields are plain bools/ints (no secret markers), so they survive
    strip_secret_keys and are exposed in MCP payloads automatically (FR-030)."""
    from backend.mcp.core.redact import strip_secret_keys
    cfg = {
        "account_id": "a",
        "cooloff_on_success_enabled": True, "cooloff_on_success_minutes": 30,
        "cooloff_on_double_failure_enabled": True, "cooloff_on_double_failure_minutes": 120,
        "api_key_encrypted": b"secret",  # control: this IS stripped
    }
    out = strip_secret_keys(cfg)
    assert out["cooloff_on_success_enabled"] is True
    assert out["cooloff_on_success_minutes"] == 30
    assert out["cooloff_on_double_failure_minutes"] == 120
    assert "api_key_encrypted" not in out  # secret dropped
