"""Tests for DebugTraceRepository."""

import os
import asyncpg
import pytest
import pytest_asyncio

from backend.services.debug_trace_repository import DebugTraceRepository

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


@pytest_asyncio.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(dsn=_TEST_DSN, min_size=1, max_size=3)
    except Exception:
        pytest.skip("PostgreSQL not available")
        return
    from backend.async_persistence import _MIGRATIONS
    async with p.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = await conn.fetchrow("SELECT version FROM schema_version")
        current = row["version"] if row else 0
        if not row:
            await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for ver, sql in _MIGRATIONS:
            if ver > current:
                if callable(sql):
                    await sql(conn)
                else:
                    for stmt in sql.split(";"):
                        if stmt.strip():
                            await conn.execute(stmt)
                await conn.execute("UPDATE schema_version SET version = $1", ver)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM debug_runs")
    await p.close()


@pytest.mark.asyncio
async def test_get_config_returns_defaults(pool):
    repo = DebugTraceRepository(pool)
    cfg = await repo.get_config()
    assert cfg["tracing_enabled"] is True
    assert cfg["retention_days"] == 60
    assert cfg["symbol_decision_cap"] == 200


@pytest.mark.asyncio
async def test_update_config_persists(pool):
    repo = DebugTraceRepository(pool)
    await repo.update_config(tracing_enabled=False, retention_days=30, symbol_decision_cap=50)
    cfg = await repo.get_config()
    assert cfg["tracing_enabled"] is False
    assert cfg["retention_days"] == 30
    assert cfg["symbol_decision_cap"] == 50


@pytest.mark.asyncio
async def test_create_and_finalize_run(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(
        scan_id="scan-abc", trigger_source="scheduled",
        schedule_id="sch-1", schedule_execution_id=42,
        config_snapshot={"k": "v"},
    )
    assert isinstance(run_id, int)
    await repo.finalize_run(
        run_id, phase_reached="finalized",
        total_symbols=580, completed_symbols=580, failed_symbols=0,
        num_accounts=21, dropped_event_count=0,
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM debug_runs WHERE id=$1", run_id)
    assert row["trigger_source"] == "scheduled"
    assert row["num_accounts"] == 21
    assert row["phase_reached"] == "finalized"
