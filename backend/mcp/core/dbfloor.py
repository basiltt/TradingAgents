"""Reserved DB-pool floor — G2-1 (FR-035), pure + trading-free (core).

The trading event loop (order placement, reconciliation, scanner) shares the
asyncpg pool with MCP read tools + sweep backtests. To guarantee a sweep fan-out
cannot starve the live loop of a connection, MCP/sweep acquisitions are capped at
`pool_max - live_floor`, where `live_floor` is a measured reserve for trading.

This module is pure arithmetic + a small concurrency gate (a counter, no I/O), so
it stays under the core import-linter contract and is deterministic to test. The
actual `pool.acquire()` wrapping lives in the composition layer (mount/services).
"""
from __future__ import annotations

import threading


def compute_mcp_acquire_cap(*, pool_max: int, live_floor: int, requested: int | None = None) -> int:
    """Max concurrent DB acquisitions MCP/sweeps may hold.

    = pool_max - live_floor, floored at 0, and clamped to `requested` when given.
    """
    available = max(0, pool_max - live_floor)
    if requested is not None:
        return min(available, max(0, requested))
    return available


def db_budget_ok(*, pool_max: int, live_floor: int, mcp_cap: int) -> bool:
    """True iff reserving the live floor AND granting mcp_cap fits within pool_max.

    Used by enable preflight (FR-035 / invariant 7): refuse to enable if the
    configured MCP cap plus the reserved trading floor would exceed the pool.
    """
    return (live_floor + mcp_cap) <= pool_max and live_floor >= 0 and mcp_cap >= 0


class DbFloor:
    """A bounded-permit gate enforcing the MCP acquisition cap.

    `try_acquire()` grants a permit while fewer than `mcp_cap` are outstanding,
    else refuses (the caller must wait / shed). `release()` frees one. Thread-safe
    (the ProcessPool parent + the event loop may both touch it). No DB handle here
    — it only counts permits; the composition layer pairs each granted permit with
    a real `pool.acquire()`.
    """

    def __init__(self, *, pool_max: int, live_floor: int, requested: int | None = None) -> None:
        self.pool_max = pool_max
        self.live_floor = live_floor
        self.mcp_cap = compute_mcp_acquire_cap(
            pool_max=pool_max, live_floor=live_floor, requested=requested
        )
        self._outstanding = 0
        self._lock = threading.Lock()

    @property
    def budget_ok(self) -> bool:
        return db_budget_ok(pool_max=self.pool_max, live_floor=self.live_floor, mcp_cap=self.mcp_cap)

    def try_acquire(self) -> bool:
        with self._lock:
            if self._outstanding < self.mcp_cap:
                self._outstanding += 1
                return True
            return False

    def release(self) -> None:
        with self._lock:
            if self._outstanding > 0:
                self._outstanding -= 1
