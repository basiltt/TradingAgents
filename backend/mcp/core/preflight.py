"""Enable preflight — TASK-P0-10.

A pure, ordered invariant check that must pass before OFF->ON. Unconditional
invariants always apply; the shm/live-SLI invariants apply only when the
optimizer (sweep) group is enabled — so MCP is enableable in P0-P3 without the
P4 sweep machinery.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.mcp.core.netguard import _is_loopback_host

EXPECTED_SCHEMA_VERSION = 44


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    failed_invariant: str = ""


def run_preflight(
    config,
    *,
    schema_version: int,
    optimizer_enabled: bool,
    single_worker_or_leader: bool = True,
    db_budget_ok: bool = True,
    shm_free_ok: bool = True,
    live_slis_present: bool = True,
) -> PreflightResult:
    """Return ok / the first failed invariant name."""
    # 1. token set + well-formed (sha256 hex)
    h = config.access_token_hash
    if not h or len(h) != 64 or not all(c in "0123456789abcdef" for c in h.lower()):
        return PreflightResult(False, "token_not_set_or_weak")
    # 2. loopback bind
    if not _is_loopback_host(config.bind_host):
        return PreflightResult(False, "bind_host_not_loopback")
    # 3. read-only safe mode for first enable
    if not config.safe_mode_flags.get("read_only", False):
        return PreflightResult(False, "safe_mode_not_read_only")
    # 4. no live-money tier on first enable
    if config.capability_tier == "LIVE_MONEY" and not config.safe_mode_flags.get("allow_real_trades", False):
        return PreflightResult(False, "live_money_tier_without_optin")
    # 5. migrations at the expected version
    if schema_version < EXPECTED_SCHEMA_VERSION:
        return PreflightResult(False, "migration_version_behind")
    # 6. single-worker or leader
    if not single_worker_or_leader:
        return PreflightResult(False, "multi_worker_without_leader")
    # 7. DB connection budget
    if not db_budget_ok:
        return PreflightResult(False, "db_pool_budget_exceeds_max_connections")
    # 8/9. optimizer-only invariants
    if optimizer_enabled:
        if not shm_free_ok:
            return PreflightResult(False, "shm_free_space_below_snapshot_budget")
        if not live_slis_present:
            return PreflightResult(False, "breaker_live_slis_absent")
    return PreflightResult(True, "")
