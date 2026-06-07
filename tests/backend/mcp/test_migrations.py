"""Migration v43/v44 tests — TASK-P0-01.

DB-free: contiguity + the v43/v44 entries exist.
DB-backed (skipped if no Postgres): apply on a scratch schema and verify the six
MCP tables, the singleton fail-safe defaults, idempotent re-apply, and the
additive backtest_runs columns.
"""
from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)

_MCP_TABLES = [
    "mcp_config",
    "mcp_sweep_jobs",
    "mcp_sweep_results",
    "mcp_audit_log",
    "mcp_proposals",
    "mcp_tokens",
]


def test_migration_versions_contiguous_and_unique():
    from backend.async_persistence import _MIGRATIONS

    versions = [v for v, _ in _MIGRATIONS]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions)), "duplicate migration version"
    # contiguous 1..max
    assert versions == list(range(1, versions[-1] + 1))
    # v43 + v44 present, v43 is a callable, v44 is a string
    by_ver = dict(_MIGRATIONS)
    assert 43 in by_ver and callable(by_ver[43])
    assert 44 in by_ver and isinstance(by_ver[44], str)
    assert by_ver[-1 if False else 44]  # sanity
    assert max(versions) == 45


async def _apply_all(conn):
    """Apply every migration (callable-aware) into the current connection's schema."""
    from backend.async_persistence import _MIGRATIONS

    await conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = await conn.fetchrow("SELECT version FROM schema_version")
    if not row:
        await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        current = 0
    else:
        current = row["version"]
    for ver, sql in _MIGRATIONS:
        if ver <= current:
            continue
        if callable(sql):
            await sql(conn)
        else:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)
        await conn.execute("UPDATE schema_version SET version = $1", ver)


@pytest_asyncio.fixture
async def scratch_conn():
    """A connection in an isolated schema so the real DB is untouched."""
    try:
        conn = await asyncpg.connect(dsn=_TEST_DSN, timeout=5)
    except Exception:
        pytest.skip("PostgreSQL not available")
        return
    schema = "mcp_mig_test"
    await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    await conn.execute(f"CREATE SCHEMA {schema}")
    await conn.execute(f"SET search_path TO {schema}")
    try:
        yield conn
    finally:
        await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_v43_creates_six_tables_and_singleton(scratch_conn):
    await _apply_all(scratch_conn)
    for tbl in _MCP_TABLES:
        exists = await scratch_conn.fetchval(
            "SELECT to_regclass($1)", f"mcp_mig_test.{tbl}"
        )
        assert exists is not None, f"{tbl} not created"
    # singleton row with fail-safe defaults
    row = await scratch_conn.fetchrow("SELECT enabled, capability_tier, safe_mode_flags FROM mcp_config WHERE id=1")
    assert row is not None
    assert row["enabled"] is False
    assert row["capability_tier"] == "READ_ONLY"
    import json

    flags = json.loads(row["safe_mode_flags"]) if isinstance(row["safe_mode_flags"], str) else row["safe_mode_flags"]
    assert flags == {"read_only": True, "allow_real_trades": False, "allow_debug": False}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_v43_reapply_idempotent(scratch_conn):
    await _apply_all(scratch_conn)
    # re-run just v43 callable — must not error (IF NOT EXISTS + guarded FK)
    from backend.async_persistence import _migrate_mcp_v43

    await _migrate_mcp_v43(scratch_conn)
    # FK constraint exists exactly once
    n = await scratch_conn.fetchval(
        "SELECT count(*) FROM pg_constraint WHERE conname='fk_mcp_best_result'"
    )
    assert n == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_v44_additive_backtest_columns(scratch_conn):
    await _apply_all(scratch_conn)
    cols = await scratch_conn.fetch(
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_schema='mcp_mig_test' AND table_name='backtest_runs' "
        "AND column_name IN ('source','sweep_id')"
    )
    names = {c["column_name"] for c in cols}
    assert names == {"source", "sweep_id"}
