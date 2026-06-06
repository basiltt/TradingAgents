"""Regression tests for the 3-feature merge hardening (backtest + debug + caching).

These guard the specific gaps found during the post-merge senior review:
  1. analysis_price must be PERSISTED by AsyncAnalysisDB.insert_scan_result — it is
     read back by the backtest signal loader; if it is dropped on write, the
     backtest price-drift filter silently no-ops (every row NULL), diverging from
     live trading.
  2. DebugTraceRecorder.open_run must be time-bounded — it is awaited on the
     scan/trade-leading path; a saturated pool must not stall trade placement.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fix #1 — analysis_price is persisted in insert_scan_result (async path)
# ---------------------------------------------------------------------------

class _CapturingPool:
    """Minimal asyncpg-pool stand-in that records the last fetchrow call."""

    def __init__(self, returned_id: int = 1):
        self.last_sql: str | None = None
        self.last_args: tuple = ()
        self._returned_id = returned_id

    async def fetchrow(self, sql, *args):
        self.last_sql = sql
        self.last_args = args
        return {"id": self._returned_id}


def _make_db_with_pool(pool):
    """Build an AsyncAnalysisDB without connecting, injecting a fake pool."""
    from backend.async_persistence import AsyncAnalysisDB
    db = AsyncAnalysisDB.__new__(AsyncAnalysisDB)
    db._closed = False  # the `pool` property checks this before returning
    db._pool = pool  # type: ignore[attr-defined]
    return db


@pytest.mark.asyncio
async def test_insert_scan_result_persists_analysis_price():
    """analysis_price must appear in the INSERT column list AND be bound."""
    pool = _CapturingPool()
    db = _make_db_with_pool(pool)

    await db.insert_scan_result(
        "scan-1",
        {
            "ticker": "BTCUSDT", "status": "completed", "direction": "buy",
            "confidence": "high", "score": 8, "signal_source": "trader",
            "analysis_price": 64250.5,
        },
    )

    assert "analysis_price" in pool.last_sql, "INSERT must name the analysis_price column"
    # The bound value must be the float we passed (last positional arg, $10).
    assert 64250.5 in pool.last_args, "analysis_price value must be bound into the INSERT"


@pytest.mark.asyncio
async def test_insert_scan_result_analysis_price_absent_binds_none():
    """When the result omits analysis_price, NULL is bound (not a crash, not 0)."""
    pool = _CapturingPool()
    db = _make_db_with_pool(pool)

    await db.insert_scan_result(
        "scan-1",
        {"ticker": "ETHUSDT", "status": "completed", "direction": "sell",
         "confidence": "moderate", "score": -6},
    )

    # analysis_price is the final bind ($10) — must be None when absent.
    assert pool.last_args[-1] is None


@pytest.mark.asyncio
async def test_insert_scan_result_rejects_nonpositive_analysis_price():
    """Defensive coercion: zero / negative / non-numeric price stored as NULL."""
    for bad in (0, -5.0, "not-a-number"):
        pool = _CapturingPool()
        db = _make_db_with_pool(pool)
        await db.insert_scan_result(
            "scan-1",
            {"ticker": "X", "status": "completed", "direction": "buy",
             "confidence": "low", "score": 1, "analysis_price": bad},
        )
        assert pool.last_args[-1] is None, f"price {bad!r} must coerce to NULL"


@pytest.mark.asyncio
async def test_insert_scan_result_on_conflict_preserves_existing_price():
    """The ON CONFLICT clause must COALESCE so a re-insert without a price does
    not wipe a previously stored analysis_price."""
    pool = _CapturingPool()
    db = _make_db_with_pool(pool)
    await db.insert_scan_result(
        "scan-1",
        {"ticker": "X", "status": "completed", "direction": "buy",
         "confidence": "low", "score": 1},
    )
    assert "COALESCE(EXCLUDED.analysis_price" in pool.last_sql.replace("\n", " ")


# ---------------------------------------------------------------------------
# Fix #5 — open_run is time-bounded so a slow pool can't stall trade placement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_run_times_out_and_fails_open():
    """If create_run hangs (pool saturated), open_run must NOT block the caller
    indefinitely — it times out, sets run_id=None, and returns (fail-open)."""
    from backend.services import debug_trace_recorder as mod
    from backend.services.debug_trace_recorder import DebugTraceRecorder, RunContext

    repo = MagicMock()

    async def _hang(**kwargs):
        await asyncio.sleep(60)  # simulate a stalled DB acquire

    repo.create_run = AsyncMock(side_effect=_hang)
    rec = DebugTraceRecorder(repo)
    rec._enabled = True
    ctx = RunContext(scan_id="s", trigger_source="manual")

    # Shrink the timeout so the test is fast; proves the wait_for path is wired.
    original = mod._OPEN_RUN_TIMEOUT_S
    mod._OPEN_RUN_TIMEOUT_S = 0.05
    try:
        await asyncio.wait_for(rec.open_run(ctx), timeout=2.0)  # must return well before 60s
    finally:
        mod._OPEN_RUN_TIMEOUT_S = original

    assert ctx.run_id is None, "a timed-out open_run must fail open (run_id=None)"


@pytest.mark.asyncio
async def test_open_run_disabled_is_noop():
    """Kill-switch: a disabled recorder never touches the DB."""
    from backend.services.debug_trace_recorder import DebugTraceRecorder, RunContext

    repo = MagicMock()
    repo.create_run = AsyncMock()
    rec = DebugTraceRecorder(repo)
    rec._enabled = False
    ctx = RunContext(scan_id="s", trigger_source="manual")

    await rec.open_run(ctx)

    assert ctx.run_id is None
    repo.create_run.assert_not_called()
