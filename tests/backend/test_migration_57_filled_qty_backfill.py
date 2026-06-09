"""Unit tests for migration 57 — the one-time filled_qty backfill.

Migration 57 (`_backfill_open_trade_filled_qty`) repairs live trades that were
opened under the OLD `filled_qty = entry-fill` semantic so they stop computing
`remaining_qty = qty - filled_qty = 0` (which made manual close reject them with
"No remaining quantity to close").

These tests pin the BEHAVIORAL CONTRACT of the migration without a live Postgres:
the exact set of statuses it touches, the `filled_qty > 0` idempotency guard, and
the deliberate exclusion of `partially_closed` (whose filled_qty is legitimately a
closed amount under the new semantic). They run against a fake asyncpg connection
that captures the SQL, plus a guard test that the migration is wired into the
registry at v57.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest

from backend.async_persistence import _MIGRATIONS, _backfill_open_trade_filled_qty


def _normalize(sql: str) -> str:
    """Collapse whitespace so assertions are layout-independent."""
    return re.sub(r"\s+", " ", sql).strip().lower()


# ── Registry wiring ────────────────────────────────────────────────────────


def test_migration_57_registered_as_last_callable() -> None:
    versions = [v for v, _ in _MIGRATIONS]
    assert versions == sorted(versions), "migration versions must be ascending"
    assert len(versions) == len(set(versions)), "no duplicate migration versions"
    assert versions[-1] == 57, "v57 must be the newest migration"

    last_version, last_fn = _MIGRATIONS[-1]
    assert last_version == 57
    assert callable(last_fn), "v57 must be a callable migration"
    assert last_fn is _backfill_open_trade_filled_qty


# ── Behavioral contract of the backfill SQL ────────────────────────────────


@pytest.fixture()
def captured_conn() -> AsyncMock:
    """A fake asyncpg conn that records the single fetchval SQL the migration runs."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)
    return conn


@pytest.mark.asyncio
async def test_backfill_resets_only_live_unclosed_statuses(captured_conn: AsyncMock) -> None:
    await _backfill_open_trade_filled_qty(captured_conn)

    assert captured_conn.fetchval.await_count == 1, "migration must run exactly one statement"
    sql = _normalize(captured_conn.fetchval.await_args.args[0])

    # Sets filled_qty to 0 on the trades table.
    assert "update trades" in sql
    assert "set filled_qty = 0" in sql

    # Touches ONLY the three live, not-yet-closed statuses.
    assert "status in ('open', 'partially_filled', 'closing')" in sql


@pytest.mark.asyncio
async def test_backfill_excludes_partially_closed_and_terminal(captured_conn: AsyncMock) -> None:
    """partially_closed/closed/cancelled/failed must NOT appear in the predicate.

    partially_closed is the dangerous one: under the new semantic its filled_qty
    legitimately records the already-closed amount, so resetting it to 0 would
    INFLATE remaining_qty and let a user close more than they actually hold.
    """
    await _backfill_open_trade_filled_qty(captured_conn)
    sql = _normalize(captured_conn.fetchval.await_args.args[0])

    # The status filter is an allowlist that must exclude these exact tokens.
    status_clause = sql.split("status in", 1)[1]
    assert "partially_closed" not in status_clause
    assert "'closed'" not in status_clause
    assert "cancelled" not in status_clause
    assert "failed" not in status_clause
    assert "pending" not in status_clause


@pytest.mark.asyncio
async def test_backfill_is_guarded_on_positive_filled_qty(captured_conn: AsyncMock) -> None:
    """Idempotency / no-op-on-fresh-DB guard: only rewrite rows that carry a stale value."""
    await _backfill_open_trade_filled_qty(captured_conn)
    sql = _normalize(captured_conn.fetchval.await_args.args[0])

    assert "filled_qty is not null" in sql
    assert "filled_qty > 0" in sql


@pytest.mark.asyncio
async def test_backfill_logs_repaired_row_count(captured_conn: AsyncMock, caplog) -> None:
    captured_conn.fetchval = AsyncMock(return_value=7)

    with caplog.at_level("INFO"):
        await _backfill_open_trade_filled_qty(captured_conn)

    assert any(
        getattr(rec, "rows_repaired", None) == 7
        for rec in caplog.records
    ), "migration must log how many rows it repaired (auditability)"


@pytest.mark.asyncio
async def test_backfill_handles_none_count_without_error(captured_conn: AsyncMock) -> None:
    """fetchval may return None on some drivers; the log coercion must not blow up."""
    captured_conn.fetchval = AsyncMock(return_value=None)
    await _backfill_open_trade_filled_qty(captured_conn)  # must not raise
