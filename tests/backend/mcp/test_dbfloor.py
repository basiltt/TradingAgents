"""Reserved DB-pool floor tests — G2-1 (FR-035).

The trading loop MUST keep a guaranteed slice of the asyncpg pool; MCP/sweep
acquisitions are capped below pool_max minus that reserved live floor, so a fan-
out of sweep backtests can never starve order placement / reconciliation of a
connection. Pure arithmetic — no DB, deterministic.
"""
from __future__ import annotations

import pytest

from backend.mcp.core.dbfloor import (
    DbFloor,
    compute_mcp_acquire_cap,
    db_budget_ok,
)


def test_mcp_cap_reserves_the_live_floor():
    # pool max 20, reserve 8 for trading → MCP may use at most 12
    assert compute_mcp_acquire_cap(pool_max=20, live_floor=8) == 12


def test_mcp_cap_never_negative():
    assert compute_mcp_acquire_cap(pool_max=5, live_floor=8) == 0


def test_mcp_cap_leaves_at_least_floor_even_with_requested_cap():
    # an explicit MCP request larger than what's left is clamped
    assert compute_mcp_acquire_cap(pool_max=20, live_floor=8, requested=100) == 12
    # a smaller request is honored
    assert compute_mcp_acquire_cap(pool_max=20, live_floor=8, requested=3) == 3


def test_db_budget_ok_true_when_floor_fits():
    # pool max 20, floor 8, mcp wants 6 → 8 + 6 = 14 <= 20 → ok
    assert db_budget_ok(pool_max=20, live_floor=8, mcp_cap=6) is True


def test_db_budget_ok_false_when_floor_plus_mcp_exceeds_max():
    assert db_budget_ok(pool_max=10, live_floor=8, mcp_cap=6) is False


def test_dbfloor_dataclass_caps_acquisitions():
    floor = DbFloor(pool_max=20, live_floor=8)
    assert floor.mcp_cap == 12
    assert floor.budget_ok is True
    # a gate that permits up to mcp_cap concurrent MCP acquisitions
    permits = [floor.try_acquire() for _ in range(15)]
    assert sum(permits) == 12  # only 12 granted, the rest refused
    floor.release()
    assert floor.try_acquire() is True  # a slot freed
