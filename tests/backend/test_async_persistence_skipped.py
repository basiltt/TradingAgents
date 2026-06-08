"""Async persistence coverage for scanner skipped_count hydration.

The SYNC persistence path (backend/persistence.py) is covered by
tests/backend/test_persistence_scanner.py. The ASYNC path
(backend/async_persistence.py, asyncpg, ``$1`` placeholders) is what runs in
PRODUCTION, and its ``skipped_count`` hydration in ``list_scans`` / ``get_scan``
had no direct test — a typo in the async SQL (e.g. a misnamed column or a wrong
``signal_source`` literal) would go uncaught. These tests close that gap by
exercising the real async methods against the live test DB.

Modeled on tests/backend/test_analysis_service.py (event_loop + db fixtures
driving AsyncAnalysisDB via run_until_complete) and on the skipped_count cases
in tests/backend/test_persistence_scanner.py. Skips gracefully when PostgreSQL
is unavailable. Each test cleans up the exact rows it inserts in a finally
block so it never pollutes the shared test DB.
"""

import asyncio
import os

import asyncpg
import psycopg2
import pytest

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


def _ensure_test_db():
    """Skip the whole module if PostgreSQL is down; create the test DB if missing.

    Mirrors the guard in test_persistence_scanner.py so this module behaves
    identically (SKIP, not ERROR) when no database is reachable.
    """
    try:
        base_dsn = _TEST_DSN.rsplit("/", 1)[0] + "/postgres"
        conn = psycopg2.connect(base_dsn)
        conn.autocommit = True
        cur = conn.cursor()
        db_name = _TEST_DSN.rsplit("/", 1)[1].split("?")[0]
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{db_name}"')
        conn.close()
    except psycopg2.OperationalError:
        pytest.skip("PostgreSQL not available", allow_module_level=True)


_ensure_test_db()


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def db(event_loop):
    from backend.async_persistence import AsyncAnalysisDB

    _db = AsyncAnalysisDB(dsn=_TEST_DSN)
    try:
        event_loop.run_until_complete(_db.connect())
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    return _db


async def _delete_scans(db, *scan_ids):
    """Remove scan_results then scans for the given ids (FK-safe order)."""
    ids = list(scan_ids)
    await db.pool.execute("DELETE FROM scan_results WHERE scan_id = ANY($1)", ids)
    await db.pool.execute("DELETE FROM scans WHERE scan_id = ANY($1)", ids)


def test_async_list_and_get_scan_hydrate_skipped_count(db, event_loop):
    """list_scans AND get_scan report skipped_count==2 for the same scan, and
    raw direction_counts['hold'] still counts ALL holds (including skipped)."""
    scan_id = "async-skip-test-mixed-1"

    async def _test():
        # Defensive pre-clean so a crashed prior run can't break the INSERT
        # (scan_id is the primary key; insert_scan does a plain INSERT).
        await _delete_scans(db, scan_id)
        try:
            await db.insert_scan({
                "scan_id": scan_id,
                "status": "completed",
                "started_at": "2025-06-08T00:00:00.000000Z",
                "total": 4,
            })
            # 2 ta_prefilter holds (skipped), 1 structured hold, 1 structured buy.
            await db.insert_scan_result(scan_id, {"ticker": "BTC", "score": 5, "status": "completed", "direction": "buy", "signal_source": "structured"})
            await db.insert_scan_result(scan_id, {"ticker": "ETH", "score": 0, "status": "completed", "direction": "hold", "signal_source": "ta_prefilter"})
            await db.insert_scan_result(scan_id, {"ticker": "SOL", "score": 0, "status": "completed", "direction": "hold", "signal_source": "ta_prefilter"})
            await db.insert_scan_result(scan_id, {"ticker": "XRP", "score": 0, "status": "completed", "direction": "hold", "signal_source": "structured"})

            # --- list_scans (returns up to 50 scans; filter to ours) ---
            scans = await db.list_scans()
            mine = next((s for s in scans if s["scan_id"] == scan_id), None)
            assert mine is not None, "inserted scan missing from list_scans()"
            assert mine["skipped_count"] == 2
            # direction_counts is RAW: all three holds counted, skipped included.
            assert mine["direction_counts"].get("hold") == 3
            assert mine["direction_counts"].get("buy") == 1

            # --- get_scan (single scan, full results) ---
            scan = await db.get_scan(scan_id)
            assert scan is not None
            assert scan["skipped_count"] == 2
            assert len(scan["results"]) == 4
        finally:
            await _delete_scans(db, scan_id)

    event_loop.run_until_complete(_test())


def test_async_skipped_count_zero_when_no_prefilter(db, event_loop):
    """Both list_scans and get_scan report skipped_count==0 when the scan has
    no ta_prefilter rows."""
    scan_id = "async-skip-test-zero-1"

    async def _test():
        await _delete_scans(db, scan_id)
        try:
            await db.insert_scan({
                "scan_id": scan_id,
                "status": "completed",
                "started_at": "2025-06-08T00:00:00.000000Z",
                "total": 2,
            })
            await db.insert_scan_result(scan_id, {"ticker": "BTC", "score": 5, "status": "completed", "direction": "buy", "signal_source": "structured"})
            await db.insert_scan_result(scan_id, {"ticker": "ETH", "score": 1, "status": "completed", "direction": "hold", "signal_source": "structured"})

            scans = await db.list_scans()
            mine = next((s for s in scans if s["scan_id"] == scan_id), None)
            assert mine is not None, "inserted scan missing from list_scans()"
            assert mine["skipped_count"] == 0

            scan = await db.get_scan(scan_id)
            assert scan is not None
            assert scan["skipped_count"] == 0
        finally:
            await _delete_scans(db, scan_id)

    event_loop.run_until_complete(_test())
