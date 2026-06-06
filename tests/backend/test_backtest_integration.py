"""Postgres-backed integration tests for the backtest service (Phase 7).

These exercise the REAL asyncpg persistence path that the Phase 5 unit suite
mocks: results/trades round-trip, transactional rollback on a mid-write failure,
and the 3-slot concurrency cap. They require a live Postgres test database and
are SKIPPED when BACKTEST_TEST_DATABASE_URL is not set, so CI without a database
stays green while the tests remain runnable wherever a DB is provided.

Run locally with, e.g.:
    BACKTEST_TEST_DATABASE_URL=postgresql://localhost/tradingagents_test \
        python -m pytest tests/backend/test_backtest_integration.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

try:
    import pytest_asyncio
except ImportError:  # pragma: no cover - skip path handles this
    pytest_asyncio = None

_DB_URL = os.environ.get("BACKTEST_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _DB_URL,
    reason="BACKTEST_TEST_DATABASE_URL not set — Postgres integration tests skipped",
)

# asyncpg is only imported lazily inside fixtures so the module still collects
# (and skips) cleanly in environments where it isn't installed.


@pytest_asyncio.fixture
async def pool():
    import asyncpg

    pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=5)
    try:
        yield pool
    finally:
        await pool.close()


class _PoolDB:
    """Minimal DB wrapper exposing a live asyncpg pool via `.pool`, matching the
    single attribute BacktestService actually uses (the production AsyncAnalysisDB
    exposes the same `.pool` property after connect())."""

    def __init__(self, pool):
        self.pool = pool


def _sample_result():
    """A SimulationResult-shaped object the service knows how to persist."""
    from backend.schemas.backtest_schemas import SimulationResult

    return SimulationResult(
        trades=[
            {
                "symbol": "BTCUSDT",
                "side": "Buy",  # schema CHECK(side IN ('Buy','Sell')) — must be capitalized
                "entry_price": 50000.0,
                "exit_price": 50250.0,
                "qty": 0.1,
                "leverage": 10,
                "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "exit_time": datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                "pnl": 38.97,
                "pnl_pct": 3.9,
                "fees_paid": 5.53,
                "close_reason": "tp",
                "mfe_pct": 5.0,
                "mae_pct": -1.0,
                "signal_score": 8,
                "signal_confidence": "high",
                "scan_id": "scan-1",
            }
        ],
        equity_curve=[{"ts": datetime(2026, 1, 1, tzinfo=timezone.utc), "equity": 10038.97}],
        metrics={"net_profit": 38.97, "final_equity": 10038.97, "total_trades": 1},
        warnings=[],
    )


@pytest.mark.integration
class TestPersistenceRoundTrip:
    @pytest.mark.asyncio
    async def test_persist_then_read_back(self, pool):
        """_persist_results writes results+trades atomically; a read sees them."""
        from backend.services.backtest_service import BacktestService

        run_id = str(uuid.uuid4())
        db = _PoolDB(pool)
        service = BacktestService(db=db)

        # Seed a run row so the FK/UPDATE targets exist.
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO backtest_runs (id, status, config, scan_source, created_at) "
                "VALUES ($1, 'running', '{}'::jsonb, '{}'::jsonb, now())",
                run_id,
            )

        await service._persist_results(run_id, _sample_result())

        async with pool.acquire() as conn:
            res = await conn.fetchrow(
                "SELECT metrics FROM backtest_results WHERE run_id = $1", run_id
            )
            trades = await conn.fetch(
                "SELECT symbol, pnl FROM backtest_trades WHERE run_id = $1", run_id
            )
            status = await conn.fetchval(
                "SELECT status FROM backtest_runs WHERE id = $1", run_id
            )

        assert res is not None
        assert len(trades) == 1
        assert trades[0]["symbol"] == "BTCUSDT"
        # Atomic completion invariant: results exist ⟺ status='completed'.
        assert status == "completed"

    @pytest.mark.asyncio
    async def test_rollback_leaves_no_orphan_results(self, pool):
        """If trade insertion fails mid-transaction, the results upsert rolls back
        too — no orphan results row, status not flipped to completed."""
        from backend.services.backtest_service import BacktestService

        run_id = str(uuid.uuid4())
        db = _PoolDB(pool)
        service = BacktestService(db=db)

        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO backtest_runs (id, status, config, scan_source, created_at) "
                "VALUES ($1, 'running', '{}'::jsonb, '{}'::jsonb, now())",
                run_id,
            )

        bad = _sample_result()
        # Force a mid-batch insert failure that genuinely RAISES (not one the
        # service's _num() coerces to NULL): an invalid `side` violates the
        # backtest_trades CHECK(side IN ('Buy','Sell')) constraint.
        bad.trades[0]["side"] = "INVALID_SIDE"

        with pytest.raises(Exception):
            await service._persist_results(run_id, bad)

        async with pool.acquire() as conn:
            res = await conn.fetchrow(
                "SELECT 1 FROM backtest_results WHERE run_id = $1", run_id
            )
            status = await conn.fetchval(
                "SELECT status FROM backtest_runs WHERE id = $1", run_id
            )

        assert res is None  # rolled back — no orphan results
        assert status != "completed"


@pytest.mark.integration
class TestConcurrencyCap:
    @pytest.mark.asyncio
    async def test_three_slot_cap_rejects_when_full(self, pool):
        """The service admits at most _MAX_CONCURRENT concurrent runs: once all
        slots are reserved, create_backtest raises BacktestBusyError before any DB
        write (the reservation is synchronous, pre-await)."""
        from backend.services.backtest_service import (
            BacktestService,
            BacktestBusyError,
            _MAX_CONCURRENT,
        )

        db = _PoolDB(pool)
        service = BacktestService(db=db)

        # Saturate the slot counter (simulating in-flight runs).
        service._active_slots = _MAX_CONCURRENT

        config = {
            "starting_capital": 10000.0,
            "date_range_start": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "date_range_end": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "scan_source": {"mode": "date_range"},
            "simulation_interval": "5m",
            "leverage": 10,
            "capital_pct": 5.0,
            "take_profit_pct": 5.0,
            "stop_loss_pct": 5.0,
        }
        with pytest.raises(BacktestBusyError):
            await service.create_backtest(config)
        # The rejected create must not have consumed an extra slot.
        assert service._active_slots == _MAX_CONCURRENT
