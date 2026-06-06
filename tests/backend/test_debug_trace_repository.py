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
        # Reset the debug_config singleton to schema defaults so the suite is
        # re-run-safe (test_update_config_persists mutates this row).
        await conn.execute(
            "UPDATE debug_config SET tracing_enabled=TRUE, retention_days=60, "
            "symbol_decision_cap=200, updated_at=now() WHERE id=1"
        )
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


@pytest.mark.asyncio
async def test_bulk_insert_events_and_read_back(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-bulk", trigger_source="manual")
    await repo.bulk_insert(
        account_traces=[{
            "run_id": run_id, "account_id": "acc-1", "account_label": "Dad - Demo",
            "execution_mode": "batch", "final_stopped_reason": None,
            "gate_that_stopped": None, "rescued_by_recheck": True,
            "base_capital": 500.1, "equity_at_start": 510.0, "positions_at_start_count": 3,
            "trades_executed": 3, "trades_failed": 0, "trades_skipped": 54,
            "rules_created": [{"rule_id": "r1", "trigger_type": "EQUITY_RISE_PCT"}],
            "config_snapshot": {"max_trades": 3},
        }],
        lifecycle_events=[{
            "run_id": run_id, "account_id": "acc-1", "seq": 0,
            "phase": "post_scan_recheck", "event_type": "state_reset", "detail": {},
        }],
        symbol_decisions=[{
            "run_id": run_id, "account_id": "acc-1", "phase": "post_scan_recheck",
            "symbol": "B3USDT", "scan_score": -7, "scan_confidence": "high",
            "scan_direction": "sell", "decision": "placed", "reason_code": "placed_ok",
            "reason_detail": {}, "order_id": "o1",
        }],
        exchange_snapshots=[{
            "run_id": run_id, "account_id": "acc-1", "gate": "scan_start",
            "positions": [{"symbol": "AAPLUSDT", "size": "1"}], "position_count": 1,
            "wallet": {"totalEquity": "510"}, "equity": 510.0,
        }],
    )
    async with pool.acquire() as conn:
        a = await conn.fetchval("SELECT count(*) FROM debug_account_traces WHERE run_id=$1", run_id)
        l = await conn.fetchval("SELECT count(*) FROM debug_lifecycle_events WHERE run_id=$1", run_id)
        s = await conn.fetchval("SELECT count(*) FROM debug_symbol_decisions WHERE run_id=$1", run_id)
        x = await conn.fetchval("SELECT count(*) FROM debug_exchange_snapshots WHERE run_id=$1", run_id)
        rules_json = await conn.fetchval(
            "SELECT rules_created FROM debug_account_traces WHERE run_id=$1", run_id
        )
        snap_json = await conn.fetchval(
            "SELECT positions FROM debug_exchange_snapshots WHERE run_id=$1", run_id
        )
        base_cap = await conn.fetchval(
            "SELECT base_capital FROM debug_account_traces WHERE run_id=$1", run_id
        )
    assert (a, l, s, x) == (1, 1, 1, 1)
    import json as _json
    from decimal import Decimal as _D
    rules = _json.loads(rules_json) if isinstance(rules_json, str) else rules_json
    snap = _json.loads(snap_json) if isinstance(snap_json, str) else snap_json
    assert rules[0]["trigger_type"] == "EQUITY_RISE_PCT"
    assert snap[0]["symbol"] == "AAPLUSDT"
    assert base_cap == _D("500.1")


@pytest.mark.asyncio
async def test_delete_runs_older_than(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-old", trigger_source="scheduled")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE debug_runs SET created_at = now() - interval '100 days' WHERE id=$1", run_id
        )
    deleted = await repo.delete_runs_older_than(60)
    assert deleted >= 1
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM debug_runs WHERE id=$1", run_id) == 0


@pytest.mark.asyncio
async def test_recover_orphaned_runs(pool):
    repo = DebugTraceRepository(pool)
    orphan = await repo.create_run(scan_id="scan-crash", trigger_source="scheduled")
    done = await repo.create_run(scan_id="scan-done", trigger_source="scheduled")
    await repo.finalize_run(done, phase_reached="finalized", num_accounts=1)
    recovered = await repo.recover_orphaned_runs()
    assert recovered >= 1
    async with pool.acquire() as conn:
        o = await conn.fetchrow("SELECT exec_completed_at, phase_reached FROM debug_runs WHERE id=$1", orphan)
        d = await conn.fetchrow("SELECT phase_reached FROM debug_runs WHERE id=$1", done)
    assert o["exec_completed_at"] is not None
    assert "server_restart" in o["phase_reached"]
    assert d["phase_reached"] == "finalized"
    assert await repo.recover_orphaned_runs() == 0
