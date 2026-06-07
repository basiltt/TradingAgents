"""Shared fixtures for MCP backend tests."""
from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


async def _apply_all_migrations(conn) -> None:
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
async def mcp_pool():
    """An asyncpg pool against an isolated `mcp_test` schema with all migrations
    applied. Skips if Postgres is unavailable."""
    try:
        admin = await asyncpg.connect(dsn=_TEST_DSN, timeout=5)
    except Exception:
        pytest.skip("PostgreSQL not available")
        return
    schema = "mcp_test"
    await admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    await admin.execute(f"CREATE SCHEMA {schema}")
    await admin.close()

    pool = await asyncpg.create_pool(
        dsn=_TEST_DSN,
        min_size=1,
        max_size=5,
        server_settings={"search_path": schema},
    )
    async with pool.acquire() as conn:
        await _apply_all_migrations(conn)
    try:
        yield pool
    finally:
        await pool.close()
        admin = await asyncpg.connect(dsn=_TEST_DSN, timeout=5)
        await admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await admin.close()
