"""Cool Off Time — Phase 3 CooloffClassifier tests.

Pure unit tests for split_earliest_episode + DB-backed integration tests for
maybe_classify: arming, settlement-defer, staleness escape, idempotency, multi-episode
catch-up, fail-open, and the equal-timestamp episode SPLIT (D45 parity).
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import psycopg2
import pytest

from backend.services.cooloff_classifier import CooloffClassifier, split_earliest_episode

_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


# ── pure unit tests: split_earliest_episode ──────────────────────────────────

def _row(idx, opened, closed, net, exit_price=10.0):
    return {
        "id": uuid.UUID(int=idx), "opened_at": opened, "closed_at": closed,
        "net_pnl": net, "exit_price": exit_price, "status": "closed",
    }


def test_split_empty_returns_none():
    assert split_earliest_episode([]) is None


def test_split_single_episode_one_trade():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [_row(1, t0, t0 + timedelta(minutes=5), 7.0)]
    ep = split_earliest_episode(rows)
    assert ep is not None
    assert ep.net_pnl == 7.0
    assert len(ep.trades) == 1
    assert ep.all_settled is True


def test_split_overlapping_trades_one_episode():
    # two trades that overlap in time -> account never flat between them -> ONE episode
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        _row(1, t0, t0 + timedelta(minutes=20), 5.0),
        _row(2, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), -3.0),
    ]
    ep = split_earliest_episode(rows)
    assert len(ep.trades) == 2
    assert ep.net_pnl == 2.0  # 5 + (-3)


def test_split_gap_separates_two_episodes_returns_earliest():
    # trade A closes, THEN trade B opens (strict gap) -> two episodes; earliest = A only
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        _row(1, t0, t0 + timedelta(minutes=5), 9.0),
        _row(2, t0 + timedelta(minutes=10), t0 + timedelta(minutes=15), -4.0),
    ]
    ep = split_earliest_episode(rows)
    assert len(ep.trades) == 1
    assert ep.net_pnl == 9.0  # only the first episode


def test_split_close_at_T_open_at_T_splits(D45=True):
    # close@T and a new open@T -> account flat at T -> SPLIT (close before same-instant open)
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    boundary = t0 + timedelta(minutes=5)
    rows = [
        _row(1, t0, boundary, 6.0),                      # closes at boundary
        _row(2, boundary, boundary + timedelta(minutes=5), -2.0),  # opens at boundary
    ]
    ep = split_earliest_episode(rows)
    assert len(ep.trades) == 1
    assert ep.net_pnl == 6.0  # first episode only — they split


def test_split_unsettled_flag():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [_row(1, t0, t0 + timedelta(minutes=5), 0.0, exit_price=0.0)]  # placeholder
    ep = split_earliest_episode(rows)
    assert ep.all_settled is False


# ── DB-backed integration ────────────────────────────────────────────────────

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


async def _ensure_account(db, account_id):
    await db.pool.execute(
        """
        INSERT INTO trading_accounts (id, label, account_type, api_key_masked,
            api_key_encrypted, api_secret_encrypted, key_version, is_active, created_at, updated_at)
        VALUES ($1,'cooloff-test','demo','xxx',$2,$3,1,1,'2024-01-01T00:00:00Z','2024-01-01T00:00:00Z')
        ON CONFLICT (id) DO NOTHING
        """,
        account_id, b"enc", b"enc",
    )


async def _cleanup(db, account_id):
    await db.pool.execute("DELETE FROM trades WHERE account_id = $1", account_id)
    await db.pool.execute("DELETE FROM account_cooloff_state WHERE account_id = $1", account_id)
    await db.pool.execute("DELETE FROM trading_accounts WHERE id = $1", account_id)


async def _enable_failure_cooloff(repo, acc, minutes=60):
    await repo.upsert_settings(acc, {
        "success_enabled": False, "success_minutes": None,
        "failure_enabled": True, "failure_minutes": minutes,
        "double_success_enabled": False, "double_success_minutes": None,
        "double_failure_enabled": False, "double_failure_minutes": None,
    })


async def _insert_closed(db, acc, *, opened, closed, net, exit_price=10.0, tid=None):
    tid = tid or uuid.uuid4()
    await db.pool.execute(
        """
        INSERT INTO trades (id, account_id, symbol, side, qty, leverage, status, source,
                            opened_at, closed_at, net_pnl, exit_price)
        VALUES ($1,$2,'BTCUSDT','Buy',1,1,'closed','scanner',$3,$4,$5,$6)
        """,
        tid, acc, opened, closed, net, exit_price,
    )
    return tid


def test_classify_losing_episode_arms_failure(db, repo, event_loop):
    async def _t():
        acc = "cls-loss-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc, minutes=60)
            t0 = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
            closed = t0 + timedelta(minutes=5)
            await _insert_closed(db, acc, opened=t0, closed=closed, net=-25.0)
            clf = CooloffClassifier(db, repo, now_fn=lambda: closed + timedelta(seconds=1))
            await clf.maybe_classify(acc)
            row = await repo.get_state(acc)
            assert row["cooloff_reason"] == "failure"
            assert row["cooloff_until"] == closed + timedelta(minutes=60)  # anchored at flat instant
            assert row["consecutive_losses"] == 1
            assert row["last_processed_close_at"] == closed
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_winning_episode_no_arm_when_only_failure_enabled(db, repo, event_loop):
    async def _t():
        acc = "cls-win-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc)
            t0 = datetime(2024, 6, 2, tzinfo=timezone.utc)
            closed = t0 + timedelta(minutes=5)
            await _insert_closed(db, acc, opened=t0, closed=closed, net=40.0)
            clf = CooloffClassifier(db, repo, now_fn=lambda: closed + timedelta(seconds=1))
            await clf.maybe_classify(acc)
            row = await repo.get_state(acc)
            assert row["cooloff_until"] is None  # win, failure-only -> no arm
            assert row["consecutive_wins"] == 1  # streak still advances
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_no_settings_row_is_noop(db, repo, event_loop):
    async def _t():
        acc = "cls-nosettings-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            t0 = datetime(2024, 6, 3, tzinfo=timezone.utc)
            await _insert_closed(db, acc, opened=t0, closed=t0 + timedelta(minutes=5), net=-10.0)
            clf = CooloffClassifier(db, repo, now_fn=lambda: t0 + timedelta(minutes=6))
            await clf.maybe_classify(acc)
            assert await repo.get_state(acc) is None  # never created a row
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_skips_when_position_still_open(db, repo, event_loop):
    async def _t():
        acc = "cls-open-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc)
            t0 = datetime(2024, 6, 4, tzinfo=timezone.utc)
            await _insert_closed(db, acc, opened=t0, closed=t0 + timedelta(minutes=5), net=-10.0)
            # an OPEN scanner position -> account not flat
            await db.pool.execute(
                "INSERT INTO trades (id, account_id, symbol, side, qty, leverage, status, source, opened_at) "
                "VALUES ($1,$2,'ETHUSDT','Buy',1,1,'open','scanner',$3)",
                uuid.uuid4(), acc, t0,
            )
            clf = CooloffClassifier(db, repo, now_fn=lambda: t0 + timedelta(minutes=6))
            await clf.maybe_classify(acc)
            row = await repo.get_state(acc)
            # no classification happened (still has settings row but no streak/arm advance)
            assert (row.get("consecutive_losses") or 0) == 0
            assert row.get("cooloff_until") is None
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_alerts_when_open_trade_stuck_but_does_not_arm(db, repo, event_loop, caplog):
    """A scanner position stuck open far longer than STALE_MIN must NOT be misclassified
    as flat (no arm), but it MUST surface an ERROR alert so it isn't silently blocking
    cool-off arming forever (the reconciler closes orphans; this just makes it visible)."""
    import logging
    from backend.services.cooloff_core import STALE_MIN_MINUTES

    async def _t():
        acc = "cls-stuck-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc)
            t0 = datetime(2024, 6, 4, tzinfo=timezone.utc)
            # an OPEN scanner position opened long ago (older than STALE_MIN)
            await db.pool.execute(
                "INSERT INTO trades (id, account_id, symbol, side, qty, leverage, status, source, opened_at) "
                "VALUES ($1,$2,'ETHUSDT','Buy',1,1,'open','scanner',$3)",
                uuid.uuid4(), acc, t0,
            )
            now = t0 + timedelta(minutes=STALE_MIN_MINUTES + 60)  # well past stale
            clf = CooloffClassifier(db, repo, now_fn=lambda: now)
            with caplog.at_level(logging.ERROR):
                await clf.maybe_classify(acc)
            # still NOT armed (a genuine open position is never treated as flat)
            row = await repo.get_state(acc)
            assert row.get("cooloff_until") is None
            assert (row.get("consecutive_losses") or 0) == 0
            # but the stuck-open condition IS surfaced
            assert any("cooloff_open_trade_stuck_blocking_arming" in r.message for r in caplog.records)
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_defers_unsettled_then_classifies_after_settle(db, repo, event_loop):
    async def _t():
        acc = "cls-defer-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc)
            t0 = datetime(2024, 6, 5, 12, 0, tzinfo=timezone.utc)
            closed = t0 + timedelta(minutes=5)
            tid = await _insert_closed(db, acc, opened=t0, closed=closed, net=0.0, exit_price=0.0)  # placeholder
            now = closed + timedelta(seconds=30)
            clf = CooloffClassifier(db, repo, now_fn=lambda: now)
            await clf.maybe_classify(acc)
            row = await repo.get_state(acc)
            assert (row.get("last_processed_close_at")) is None  # deferred — not processed
            # reconciler backfills the real loss
            await db.pool.execute("UPDATE trades SET net_pnl=-15.0, exit_price=9.0 WHERE id=$1", tid)
            await clf.maybe_classify(acc)
            row2 = await repo.get_state(acc)
            assert row2["cooloff_reason"] == "failure"  # now classified
            assert row2["consecutive_losses"] == 1
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_staleness_escape_advances_neutral(db, repo, event_loop):
    async def _t():
        acc = "cls-stale-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc)
            t0 = datetime(2024, 6, 6, tzinfo=timezone.utc)
            closed = t0 + timedelta(minutes=5)
            await _insert_closed(db, acc, opened=t0, closed=closed, net=0.0, exit_price=0.0)  # never settles
            now = closed + timedelta(hours=30)  # > STALE_MIN (26h)
            clf = CooloffClassifier(db, repo, now_fn=lambda: now)
            await clf.maybe_classify(acc)
            row = await repo.get_state(acc)
            # advanced past as neutral: high-water moved, no arm, no streak change
            assert row["last_processed_close_at"] == closed
            assert row["cooloff_until"] is None
            assert (row.get("consecutive_losses") or 0) == 0
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_idempotent(db, repo, event_loop):
    async def _t():
        acc = "cls-idem-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            await _enable_failure_cooloff(repo, acc, minutes=30)
            t0 = datetime(2024, 6, 7, 12, 0, tzinfo=timezone.utc)
            closed = t0 + timedelta(minutes=5)
            await _insert_closed(db, acc, opened=t0, closed=closed, net=-10.0)
            clf = CooloffClassifier(db, repo, now_fn=lambda: closed + timedelta(seconds=1))
            await clf.maybe_classify(acc)
            await clf.maybe_classify(acc)  # second run must not re-count
            row = await repo.get_state(acc)
            assert row["consecutive_losses"] == 1  # not 2
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_classify_two_episodes_in_one_call_double_failure(db, repo, event_loop):
    async def _t():
        acc = "cls-two-" + uuid.uuid4().hex[:8]
        await _ensure_account(db, acc)
        try:
            # both single + double failure enabled
            await repo.upsert_settings(acc, {
                "success_enabled": False, "success_minutes": None,
                "failure_enabled": True, "failure_minutes": 30,
                "double_success_enabled": False, "double_success_minutes": None,
                "double_failure_enabled": True, "double_failure_minutes": 120,
            })
            t0 = datetime(2024, 6, 8, 12, 0, tzinfo=timezone.utc)
            # episode 1: loss, fully flat, then episode 2: loss (strict gap)
            c1 = t0 + timedelta(minutes=5)
            await _insert_closed(db, acc, opened=t0, closed=c1, net=-10.0)
            c2 = t0 + timedelta(minutes=20)
            await _insert_closed(db, acc, opened=t0 + timedelta(minutes=15), closed=c2, net=-8.0)
            clf = CooloffClassifier(db, repo, now_fn=lambda: c2 + timedelta(seconds=1))
            await clf.maybe_classify(acc)
            row = await repo.get_state(acc)
            # 2 consecutive losses -> double_failure fired on the 2nd; that side reset to 0
            assert row["cooloff_reason"] == "double_failure"
            assert row["consecutive_losses"] == 0
            assert row["last_processed_close_at"] == c2
        finally:
            await _cleanup(db, acc)
    event_loop.run_until_complete(_t())


def test_maybe_classify_failopen_on_repo_error(db, event_loop):
    """A repo/DB error inside classification must be swallowed (never raises)."""
    async def _t():
        class _BoomRepo:
            async def get_state(self, account_id):
                raise RuntimeError("boom")
        clf = CooloffClassifier(db, _BoomRepo())
        # must not raise
        await clf.maybe_classify("any")
    event_loop.run_until_complete(_t())
