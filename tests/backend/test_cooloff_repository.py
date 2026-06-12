"""Cool Off Time — Phase 2 DB + CooloffRepository tests (against the live test DB).

Covers migration v61 (account_cooloff_state + constraints) and CooloffRepository:
upsert_settings (column-scoped, no state clobber), read_status (no-row defaults,
remaining math, cooling boundary, corruption clamp), clear (idempotent +/- reset_streak),
count_open_scanner (pending-inclusive; excludes manual/cycle/terminal),
fetch_unprocessed_closed (composite-key ordering, NULL mark from-beginning, tiebreak),
apply_classification (max-rearm + clamp + reason-follows-until).

Skips gracefully when PostgreSQL is unavailable (mirrors test_async_persistence_skipped.py).
Each test cleans up the rows it inserts.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import psycopg2
import pytest

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


def _ensure_test_db():
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


@pytest.fixture
def repo(db):
    from backend.services.cooloff_repository import CooloffRepository
    return CooloffRepository(db)


async def _ensure_account(db, account_id: str):
    """Insert a minimal trading_accounts row (FK target) if absent."""
    await db.pool.execute(
        """
        INSERT INTO trading_accounts (
            id, label, account_type, api_key_masked, api_key_encrypted,
            api_secret_encrypted, key_version, is_active, created_at, updated_at
        ) VALUES ($1, 'cooloff-test', 'demo', 'xxx', $2, $3, 1, 1,
                  '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')
        ON CONFLICT (id) DO NOTHING
        """,
        account_id, b"enc", b"enc",
    )


async def _cleanup(db, account_id: str):
    await db.pool.execute("DELETE FROM trades WHERE account_id = $1", account_id)
    await db.pool.execute("DELETE FROM account_cooloff_state WHERE account_id = $1", account_id)
    await db.pool.execute("DELETE FROM trading_accounts WHERE id = $1", account_id)


# ── migration v61 ────────────────────────────────────────────────────────────

def test_migration_v61_table_and_constraints(db, event_loop):
    async def _t():
        # table exists
        exists = await db.pool.fetchval(
            "SELECT to_regclass('public.account_cooloff_state')"
        )
        assert exists is not None
        acc = "cooloff-mig-1"
        await _ensure_account(db, acc)
        try:
            # chk_cooloff_pair: until set but reason null -> reject
            with pytest.raises(asyncpg.PostgresError):
                await db.pool.execute(
                    "INSERT INTO account_cooloff_state (account_id, cooloff_until) "
                    "VALUES ($1, NOW())", acc,
                )
            # *_minutes CHECK: 0 rejected
            with pytest.raises(asyncpg.PostgresError):
                await db.pool.execute(
                    "INSERT INTO account_cooloff_state (account_id, success_minutes) "
                    "VALUES ($1, 0)", acc,
                )
            # valid pair ok
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason) "
                "VALUES ($1, NOW(), 'failure')", acc,
            )
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_migration_v62_account_fk_cascades_on_delete(db, event_loop):
    """Migration v62: the account FK is ON DELETE CASCADE, so deleting a trading
    account also removes its cool-off state row (the original v61 NO ACTION FK would
    block account deletion once a cool-off row existed)."""
    async def _t():
        acc = "cooloff-fk-cascade-1"
        await _ensure_account(db, acc)
        try:
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason) "
                "VALUES ($1, NOW(), 'failure')", acc,
            )
            # Deleting the parent account must NOT raise an FK violation...
            await db.pool.execute("DELETE FROM trading_accounts WHERE id = $1", acc)
            # ...and must cascade away the cool-off row.
            remaining = await db.pool.fetchval(
                "SELECT COUNT(*) FROM account_cooloff_state WHERE account_id = $1", acc,
            )
            assert remaining == 0
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_migration_v63_enabled_tier_requires_minutes(db, event_loop):
    """Migration v63: a DB-level CHECK rejects an ENABLED tier with NULL minutes
    (defense-in-depth behind the Pydantic validators + frontend gate)."""
    async def _t():
        acc = "cooloff-v63-chk-1"
        await _ensure_account(db, acc)
        try:
            # enabled + NULL minutes -> rejected by chk_cooloff_failure_enabled_needs_minutes
            with pytest.raises(asyncpg.PostgresError):
                await db.pool.execute(
                    "INSERT INTO account_cooloff_state (account_id, failure_enabled, failure_minutes) "
                    "VALUES ($1, true, NULL)", acc,
                )
            # enabled + valid minutes -> accepted
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, failure_enabled, failure_minutes) "
                "VALUES ($1, true, 60)", acc,
            )
            # disabled + NULL minutes -> accepted (the common all-OFF disable row)
            await db.pool.execute(
                "UPDATE account_cooloff_state SET failure_enabled = false, failure_minutes = NULL "
                "WHERE account_id = $1", acc,
            )
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_migration_v63_episode_index_exists(db, event_loop):
    """Migration v63: the tuned partial index for the classifier's episode query exists."""
    async def _t():
        idx = await db.pool.fetchval(
            "SELECT to_regclass('public.idx_trades_cooloff_episode')"
        )
        assert idx is not None
    event_loop.run_until_complete(_t())


# ── upsert_settings: column-scoped, no state clobber ─────────────────────────

def test_upsert_settings_does_not_clobber_state(db, repo, event_loop):
    async def _t():
        acc = "cooloff-upsert-1"
        await _ensure_account(db, acc)
        try:
            # arm a cool-off + streak directly
            future = datetime.now(timezone.utc) + timedelta(hours=2)
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason, "
                "consecutive_losses) VALUES ($1,$2,'failure',2)", acc, future,
            )
            # a settings save must NOT touch until/reason/streak
            await repo.upsert_settings(acc, {
                "success_enabled": True, "success_minutes": 30,
                "failure_enabled": False, "failure_minutes": None,
                "double_success_enabled": False, "double_success_minutes": None,
                "double_failure_enabled": False, "double_failure_minutes": None,
            })
            row = await repo.get_state(acc)
            assert row["success_enabled"] is True
            assert row["success_minutes"] == 30
            assert row["cooloff_reason"] == "failure"  # untouched
            assert row["consecutive_losses"] == 2       # untouched
            assert row["consecutive_wins"] == 0         # untouched
            assert row["cooloff_until"] == future        # EXACT — not merely non-null (P2Q-F1)
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


# ── read_status ──────────────────────────────────────────────────────────────

def test_read_status_no_row_defaults(db, repo, event_loop):
    async def _t():
        acc = "cooloff-status-none"
        await _ensure_account(db, acc)
        try:
            st = await repo.read_status(acc)
            assert st["cooling"] is False
            assert st["cooloff_until"] is None
            assert st["consecutive_wins"] == 0
            assert st["cooloff_remaining_seconds"] == 0
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_read_status_cooling_and_boundary(db, repo, event_loop):
    async def _t():
        acc = "cooloff-status-cool"
        await _ensure_account(db, acc)
        try:
            now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            until = now + timedelta(minutes=30)
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason) "
                "VALUES ($1,$2,'failure')", acc, until,
            )
            st = await repo.read_status(acc, now=now)
            assert st["cooling"] is True
            assert st["cooloff_remaining_seconds"] == 1800
            assert st["cooloff_reason"] == "failure"
            # at exactly until -> not cooling (strict now<until)
            st2 = await repo.read_status(acc, now=until)
            assert st2["cooling"] is False
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_read_status_corruption_clamp_resets(db, repo, event_loop):
    async def _t():
        acc = "cooloff-status-corrupt"
        await _ensure_account(db, acc)
        try:
            now = datetime.now(timezone.utc)
            corrupt = now + timedelta(days=400)  # > 31d clamp
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason) "
                "VALUES ($1,$2,'success')", acc, corrupt,
            )
            st = await repo.read_status(acc, now=now)
            assert st["cooling"] is False  # corrupt -> not cooling
            # and it was reset
            row = await repo.get_state(acc)
            assert row["cooloff_until"] is None
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


# ── clear ──────────────────────────────────────────────────────────────────

def test_clear_idempotent_keeps_streak(db, repo, event_loop):
    async def _t():
        acc = "cooloff-clear-1"
        await _ensure_account(db, acc)
        try:
            future = datetime.now(timezone.utc) + timedelta(hours=1)
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason, "
                "consecutive_losses) VALUES ($1,$2,'failure',2)", acc, future,
            )
            assert await repo.clear(acc) is True
            row = await repo.get_state(acc)
            assert row["cooloff_until"] is None
            assert row["consecutive_losses"] == 2  # streak preserved
            # idempotent
            assert await repo.clear(acc) is True
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_clear_with_reset_streak(db, repo, event_loop):
    async def _t():
        acc = "cooloff-clear-2"
        await _ensure_account(db, acc)
        try:
            future = datetime.now(timezone.utc) + timedelta(hours=1)
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason, "
                "consecutive_losses) VALUES ($1,$2,'failure',2)", acc, future,
            )
            await repo.clear(acc, reset_streak=True)
            row = await repo.get_state(acc)
            assert row["consecutive_losses"] == 0
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


# ── count_open_scanner ───────────────────────────────────────────────────────

async def _insert_trade(db, account_id, *, status, source, closed_at=None, net_pnl=None,
                        exit_price=None, opened_at=None, trade_id=None):
    tid = trade_id or uuid.uuid4()
    await db.pool.execute(
        """
        INSERT INTO trades (id, account_id, symbol, side, qty, leverage, status, source,
                            opened_at, closed_at, net_pnl, exit_price)
        VALUES ($1,$2,'BTCUSDT','Buy',1,1,$3,$4,$5,$6,$7,$8)
        """,
        tid, account_id, status, source,
        opened_at or datetime.now(timezone.utc), closed_at, net_pnl, exit_price,
    )
    return tid


def test_count_open_scanner_includes_pending_excludes_others(db, repo, event_loop):
    async def _t():
        acc = "cooloff-count-1"
        await _ensure_account(db, acc)
        try:
            await _insert_trade(db, acc, status="pending", source="scanner")
            await _insert_trade(db, acc, status="open", source="scanner")
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=datetime.now(timezone.utc), net_pnl=1, exit_price=10)
            await _insert_trade(db, acc, status="open", source="manual")  # excluded (non-scanner)
            async with db.pool.acquire() as conn:
                n = await repo.count_open_scanner(conn, acc)
            assert n == 2  # pending + open scanner only (manual excluded)
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


# ── fetch_unprocessed_closed ─────────────────────────────────────────────────

def test_fetch_unprocessed_null_mark_from_beginning_and_order(db, repo, event_loop):
    async def _t():
        acc = "cooloff-fetch-1"
        await _ensure_account(db, acc)
        try:
            t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=t0 + timedelta(minutes=10), net_pnl=5, exit_price=10)
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=t0 + timedelta(minutes=5), net_pnl=-3, exit_price=9)
            await _insert_trade(db, acc, status="open", source="scanner")  # not closed -> excluded
            async with db.pool.acquire() as conn:
                rows = await repo.fetch_unprocessed_closed(conn, acc, None, None)
            assert len(rows) == 2
            # ordered by closed_at asc
            assert rows[0]["closed_at"] < rows[1]["closed_at"]
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_fetch_unprocessed_respects_high_water(db, repo, event_loop):
    async def _t():
        acc = "cooloff-fetch-2"
        await _ensure_account(db, acc)
        try:
            t0 = datetime(2024, 2, 1, tzinfo=timezone.utc)
            id_a = await _insert_trade(db, acc, status="closed", source="scanner",
                                       closed_at=t0, net_pnl=1, exit_price=10)
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=t0 + timedelta(minutes=10), net_pnl=2, exit_price=11)
            async with db.pool.acquire() as conn:
                rows = await repo.fetch_unprocessed_closed(conn, acc, t0, str(id_a))
            # strictly after (t0, id_a) -> only the later trade
            assert len(rows) == 1
            assert rows[0]["closed_at"] == t0 + timedelta(minutes=10)
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


# ── apply_classification: max-rearm + clamp + reason-follows-until ───────────

def test_apply_classification_max_rearm_never_shortens(db, repo, event_loop):
    async def _t():
        acc = "cooloff-apply-1"
        await _ensure_account(db, acc)
        try:
            now = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
            long_until = now + timedelta(hours=4)
            async with db.pool.acquire() as conn:
                # first arm: long failure cool-off
                await repo.apply_classification(
                    conn, acc, new_wins=0, new_losses=0,
                    mark_at=now, mark_id=str(uuid.uuid4()),
                    cooloff_until=long_until, cooloff_reason="double_failure", now=now,
                )
                # second arm: SHORTER success cool-off -> must NOT shorten, reason stays
                short_until = now + timedelta(minutes=5)
                await repo.apply_classification(
                    conn, acc, new_wins=1, new_losses=0,
                    mark_at=now + timedelta(minutes=1), mark_id=str(uuid.uuid4()),
                    cooloff_until=short_until, cooloff_reason="success", now=now,
                )
            row = await repo.get_state(acc)
            assert row["cooloff_until"] == long_until  # longer kept
            assert row["cooloff_reason"] == "double_failure"  # reason follows the kept until
            assert row["consecutive_wins"] == 1  # streak still updated
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_apply_classification_clamps_far_future(db, repo, event_loop):
    async def _t():
        acc = "cooloff-apply-2"
        await _ensure_account(db, acc)
        try:
            now = datetime(2024, 3, 1, tzinfo=timezone.utc)
            insane = now + timedelta(days=999)
            async with db.pool.acquire() as conn:
                await repo.apply_classification(
                    conn, acc, new_wins=0, new_losses=1,
                    mark_at=now, mark_id=str(uuid.uuid4()),
                    cooloff_until=insane, cooloff_reason="failure", now=now,
                )
            row = await repo.get_state(acc)
            ceiling = now + timedelta(days=31)
            assert row["cooloff_until"] <= ceiling
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())

# ── P2 review additions (P2Q-F2/F3/F4/F5/F7/F8/F9) ───────────────────────────

def test_apply_classification_non_arming_preserves_active_cooloff(db, repo, event_loop):
    """A neutral/no-arm classification must leave an ACTIVE cool-off + reason intact
    while still advancing the streak + high-water mark (P2Q-F2)."""
    async def _t():
        acc = "cooloff-apply-noarm-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            now = datetime(2024, 4, 1, 12, 0, tzinfo=timezone.utc)
            active_until = now + timedelta(hours=3)
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason) "
                "VALUES ($1,$2,'double_failure')", acc, active_until,
            )
            mark_at = now + timedelta(minutes=1)
            mark_id = str(uuid.uuid4())
            async with db.pool.acquire() as conn:
                await repo.apply_classification(
                    conn, acc, new_wins=1, new_losses=0,
                    mark_at=mark_at, mark_id=mark_id,
                    cooloff_until=None, cooloff_reason=None, now=now,
                )
            row = await repo.get_state(acc)
            assert row["cooloff_until"] == active_until  # active cool-off untouched
            assert row["cooloff_reason"] == "double_failure"
            assert row["consecutive_wins"] == 1          # streak advanced
            assert row["last_processed_close_at"] == mark_at  # high-water persisted (P2Q-F7)
            assert str(row["last_processed_close_id"]) == mark_id
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_upsert_settings_fresh_account_insert_path(db, repo, event_loop):
    """upsert_settings on an account with NO row inserts settings + leaves state cols
    at defaults (INSERT path, not just ON CONFLICT — P2Q-F3)."""
    async def _t():
        acc = "cooloff-fresh-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await repo.upsert_settings(acc, {
                "success_enabled": False, "success_minutes": None,
                "failure_enabled": True, "failure_minutes": 45,
                "double_success_enabled": False, "double_success_minutes": None,
                "double_failure_enabled": False, "double_failure_minutes": None,
            })
            row = await repo.get_state(acc)
            assert row is not None
            assert row["failure_enabled"] is True
            assert row["failure_minutes"] == 45
            # state cols at defaults
            assert row["cooloff_until"] is None
            assert row["cooloff_reason"] is None
            assert row["consecutive_wins"] == 0
            assert row["consecutive_losses"] == 0
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_fetch_unprocessed_equal_closed_at_tiebreak_by_id(db, repo, event_loop):
    """Two closed trades sharing an identical closed_at: the composite (closed_at,id)
    high-water must return only the strictly-higher id (P2Q-F4)."""
    async def _t():
        acc = "cooloff-tie-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            t0 = datetime(2024, 5, 1, tzinfo=timezone.utc)
            id_lo = uuid.UUID("00000000-0000-0000-0000-000000000001")
            id_hi = uuid.UUID("00000000-0000-0000-0000-000000000002")
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=t0, net_pnl=1, exit_price=10, trade_id=id_lo)
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=t0, net_pnl=2, exit_price=11, trade_id=id_hi)
            async with db.pool.acquire() as conn:
                rows = await repo.fetch_unprocessed_closed(conn, acc, t0, str(id_lo))
            assert len(rows) == 1
            assert rows[0]["id"] == id_hi
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_clear_no_row_returns_false(db, repo, event_loop):
    """clear() on an account with no cool-off row returns False (P2Q-F5)."""
    async def _t():
        acc = "cooloff-clearnone-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            assert await repo.clear(acc) is False
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_count_open_scanner_status_matrix(db, repo, event_loop):
    """Every live status is counted; a terminal status is excluded (P2Q-F6)."""
    async def _t():
        acc = "cooloff-statusmx-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            for st in ("pending", "open", "partially_filled", "closing", "partially_closed"):
                await _insert_trade(db, acc, status=st, source="scanner")
            await _insert_trade(db, acc, status="cancelled", source="scanner")  # terminal
            await _insert_trade(db, acc, status="closed", source="scanner",
                                closed_at=datetime.now(timezone.utc), net_pnl=1, exit_price=10)
            async with db.pool.acquire() as conn:
                n = await repo.count_open_scanner(conn, acc)
            assert n == 5  # the 5 live statuses; cancelled + closed excluded
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_corruption_clamp_resets_reason_too(db, repo, event_loop):
    """The corruption reset nulls BOTH cooloff_until and cooloff_reason (P2Q-F8)."""
    async def _t():
        acc = "cooloff-corrupt2-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            now = datetime.now(timezone.utc)
            await db.pool.execute(
                "INSERT INTO account_cooloff_state (account_id, cooloff_until, cooloff_reason) "
                "VALUES ($1,$2,'success')", acc, now + timedelta(days=500),
            )
            await repo.read_status(acc, now=now)
            row = await repo.get_state(acc)
            assert row["cooloff_until"] is None
            assert row["cooloff_reason"] is None
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_try_lock_excludes_concurrent_holder(db, repo, event_loop):
    """try_lock returns False to a 2nd connection while a 1st holds the xact lock (P2Q-F9)."""
    async def _t():
        acc = "cooloff-lock-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            async with db.pool.acquire() as conn_a, conn_a.transaction():
                got_a = await repo.try_lock(conn_a, acc)
                assert got_a is True
                async with db.pool.acquire() as conn_b, conn_b.transaction():
                    got_b = await repo.try_lock(conn_b, acc)
                    assert got_b is False  # A holds it
            # after A's txn commits, the lock is released
            async with db.pool.acquire() as conn_c, conn_c.transaction():
                assert await repo.try_lock(conn_c, acc) is True
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())
