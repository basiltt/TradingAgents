"""Tests for CycleRepository CRUD operations."""

import os
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg
import pytest
import pytest_asyncio

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
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = await conn.fetchrow("SELECT version FROM schema_version")
        current = row["version"] if row else 0
        if not row:
            await conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for ver, sql in _MIGRATIONS:
            if ver > current:
                await conn.execute(sql)
                await conn.execute("UPDATE schema_version SET version = $1", ver)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM cycle_trades")
        await conn.execute("DELETE FROM close_rules WHERE cycle_id IS NOT NULL")
        await conn.execute("DELETE FROM trading_cycles")
    await p.close()


def _account_id() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


async def _ensure_account(pool: asyncpg.Pool, account_id: str) -> None:
    """Insert a minimal trading_accounts row if not exists."""
    await pool.execute(
        """
        INSERT INTO trading_accounts (id, label, account_type, api_key_masked, api_key_encrypted, api_secret_encrypted, created_at, updated_at)
        VALUES ($1, 'Test', 'demo', 'xxx', '\\x00', '\\x00', $2, $2)
        ON CONFLICT (id) DO NOTHING
        """,
        account_id, datetime.now(timezone.utc).isoformat(),
    )


def _cycle_config(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "scan_id": None,
        "trade_direction": "straight",
        "leverage": 10,
        "capital_pct": 5.0,
        "take_profit_pct": 10.0,
        "stop_loss_pct": 5.0,
        "min_score": 3,
        "min_confidence": "moderate",
        "signal_filter": "both",
        "max_trades": 5,
        "target_type": "percentage",
        "target_value": 10.0,
        "max_drawdown_pct": 5.0,
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.asyncio
async def test_create_cycle(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    assert isinstance(cid, int)
    row = await pool.fetchrow("SELECT * FROM trading_cycles WHERE id = $1", cid)
    assert row["status"] == "pending"
    assert row["account_id"] == acct


@pytest.mark.asyncio
async def test_create_cycle_duplicate_active(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    await repo.create_cycle(_cycle_config(acct))
    with pytest.raises(asyncpg.UniqueViolationError):
        await repo.create_cycle(_cycle_config(acct))


@pytest.mark.asyncio
async def test_get_cycle_with_trades(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        await repo.add_trade(cid, {"symbol": sym, "side": "Buy", "status": "filled"})
    result = await repo.get_cycle(cid)
    assert result is not None
    assert len(result["trades"]) == 3


@pytest.mark.asyncio
async def test_get_cycle_not_found(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    result = await repo.get_cycle(999999)
    assert result is None


@pytest.mark.asyncio
async def test_list_cycles_pagination(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct_ids = [_account_id() for _ in range(5)]
    for a in acct_ids:
        await _ensure_account(pool, a)
        await repo.create_cycle(_cycle_config(a))
    items, total = await repo.list_cycles(offset=1, limit=2)
    assert len(items) == 2
    assert total >= 5


@pytest.mark.asyncio
async def test_list_cycles_order(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct_ids = [_account_id() for _ in range(3)]
    for a in acct_ids:
        await _ensure_account(pool, a)
        await repo.create_cycle(_cycle_config(a))
    items, _ = await repo.list_cycles(limit=3)
    dates = [i["created_at"] for i in items]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_list_cycles_status_filter(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct1 = _account_id()
    acct2 = _account_id()
    await _ensure_account(pool, acct1)
    await _ensure_account(pool, acct2)
    cid1 = await repo.create_cycle(_cycle_config(acct1))
    cid2 = await repo.create_cycle(_cycle_config(acct2))
    await repo.update_status(cid2, "completed", completed_at=datetime.now(timezone.utc))
    items, total = await repo.list_cycles(status="active")
    ids = [i["id"] for i in items]
    assert cid1 in ids
    assert cid2 not in ids


@pytest.mark.asyncio
async def test_update_status_success(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    ok = await repo.update_status(cid, "placing_trades")
    assert ok is True
    row = await pool.fetchrow("SELECT status FROM trading_cycles WHERE id = $1", cid)
    assert row["status"] == "placing_trades"


@pytest.mark.asyncio
async def test_update_status_terminal(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    await repo.update_status(cid, "completed", completed_at=datetime.now(timezone.utc))
    ok = await repo.update_status(cid, "running")
    assert ok is False


@pytest.mark.asyncio
async def test_add_trade(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    tid = await repo.add_trade(cid, {"symbol": "BTCUSDT", "side": "Buy", "status": "filled"})
    assert isinstance(tid, int)


@pytest.mark.asyncio
async def test_update_trade(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    tid = await repo.add_trade(cid, {"symbol": "BTCUSDT", "side": "Buy", "status": "pending"})
    await repo.update_trade(tid, status="filled", entry_price=50000.0, filled_at=datetime.now(timezone.utc))
    row = await pool.fetchrow("SELECT status, entry_price FROM cycle_trades WHERE id = $1", tid)
    assert row["status"] == "filled"


@pytest.mark.asyncio
async def test_increment_counters(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    await repo.increment_counters(cid, placed=1)
    row = await pool.fetchrow("SELECT trades_placed FROM trading_cycles WHERE id = $1", cid)
    assert row["trades_placed"] == 1


@pytest.mark.asyncio
async def test_find_stuck_cycles(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    await repo.update_status(cid, "running")
    await pool.execute(
        "UPDATE trading_cycles SET created_at = $2 WHERE id = $1",
        cid, datetime.now(timezone.utc) - timedelta(hours=2),
    )
    stuck = await repo.find_stuck_cycles(3600)
    assert any(c["id"] == cid for c in stuck)


@pytest.mark.asyncio
async def test_find_stuck_cycles_none(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    await repo.update_status(cid, "running")
    stuck = await repo.find_stuck_cycles(3600)
    assert not any(c["id"] == cid for c in stuck)


@pytest.mark.asyncio
async def test_reconcile_counters(pool):
    from backend.services.cycle_repository import CycleRepository
    repo = CycleRepository(pool)
    acct = _account_id()
    await _ensure_account(pool, acct)
    cid = await repo.create_cycle(_cycle_config(acct))
    await repo.add_trade(cid, {"symbol": "BTCUSDT", "side": "Buy", "status": "filled"})
    await repo.add_trade(cid, {"symbol": "ETHUSDT", "side": "Buy", "status": "filled"})
    await repo.add_trade(cid, {"symbol": "SOLUSDT", "side": "Sell", "status": "failed"})
    await pool.execute(
        "UPDATE trading_cycles SET trades_placed = 99, trades_failed = 99 WHERE id = $1", cid
    )
    await repo.reconcile_counters(cid)
    row = await pool.fetchrow("SELECT trades_placed, trades_failed FROM trading_cycles WHERE id = $1", cid)
    assert row["trades_placed"] == 2
    assert row["trades_failed"] == 1
