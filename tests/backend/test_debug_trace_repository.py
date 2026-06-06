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


def test_num_coerces_float_exactly_via_str():
    from backend.services.debug_trace_repository import _num
    from decimal import Decimal
    # The whole point of _num: Decimal(str(0.1)) == Decimal("0.1"),
    # whereas the naive Decimal(0.1) == Decimal("0.1000000000000000055511151231257827021181583404541015625").
    assert _num(0.1) == Decimal("0.1")
    assert str(_num(0.1)) == "0.1"
    assert _num(500.1) == Decimal("500.1")
    assert _num(None) is None
    d = Decimal("123.45")
    assert _num(d) is d  # Decimal passes through unchanged (identity)


def test_strip_secret_keys_drops_credential_shaped_keys():
    from backend.services.debug_trace_repository import _strip_secret_keys
    out = _strip_secret_keys({
        "max_trades": 3, "llm_api_key": "x", "apiSecret": "y",
        "authToken": "z", "db_password": "p", "credentials": "c", "leverage": 5,
    })
    assert out == {"max_trades": 3, "leverage": 5}  # only non-secret keys retained
    assert _strip_secret_keys(None) == {}
    assert _strip_secret_keys("notadict") == {}


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
async def test_bulk_insert_coerces_float_scan_score_to_int(pool):
    """scan_score maps to an INT column; a stray float would fail asyncpg's binary
    COPY for the WHOLE batch. bulk_insert coerces it via int() for COPY-safety, while
    None still passes through unchanged. Without the coercion this call would raise."""
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-score-coerce", trigger_source="manual")
    await repo.bulk_insert(
        symbol_decisions=[
            {"run_id": run_id, "account_id": "acc-1", "phase": "batch",
             "symbol": "FLOATUSDT", "scan_score": 7.0, "scan_confidence": "high",
             "scan_direction": "buy", "decision": "placed", "reason_code": "placed_ok",
             "reason_detail": {}, "order_id": "o1"},
            {"run_id": run_id, "account_id": "acc-1", "phase": "batch",
             "symbol": "NONEUSDT", "scan_score": None, "scan_confidence": "low",
             "scan_direction": "sell", "decision": "skipped", "reason_code": "low_score",
             "reason_detail": {}},
        ],
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT symbol, scan_score FROM debug_symbol_decisions WHERE run_id=$1 ORDER BY symbol",
            run_id,
        )
    by_symbol = {r["symbol"]: r["scan_score"] for r in rows}
    assert by_symbol["FLOATUSDT"] == 7
    assert isinstance(by_symbol["FLOATUSDT"], int)
    assert by_symbol["NONEUSDT"] is None


@pytest.mark.asyncio
async def test_bulk_insert_strips_secrets_from_config_snapshot(pool):
    """Defense-in-depth: even if a caller passes raw config with credential-shaped
    keys, the persistence boundary strips them before they hit the DB."""
    import json as _json
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-secret", trigger_source="manual",
                                   config_snapshot={"num_configs": 1, "llm_api_key": "LEAK"})
    await repo.bulk_insert(account_traces=[{
        "run_id": run_id, "account_id": "acc-s", "rules_created": [],
        "config_snapshot": {"max_trades": 3, "api_key": "LEAK", "secret_token": "LEAK2"},
    }])
    async with pool.acquire() as conn:
        acct_cfg = await conn.fetchval(
            "SELECT config_snapshot FROM debug_account_traces WHERE run_id=$1", run_id)
        run_cfg = await conn.fetchval(
            "SELECT config_snapshot FROM debug_runs WHERE id=$1", run_id)
    acct_cfg = _json.loads(acct_cfg) if isinstance(acct_cfg, str) else acct_cfg
    run_cfg = _json.loads(run_cfg) if isinstance(run_cfg, str) else run_cfg
    assert acct_cfg == {"max_trades": 3}            # api_key + secret_token stripped
    assert run_cfg == {"num_configs": 1}            # llm_api_key stripped at create_run
    assert "api_key" not in acct_cfg and "secret_token" not in acct_cfg


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


@pytest.mark.asyncio
async def test_get_latest_run_for_scan_and_tree(pool):
    repo = DebugTraceRepository(pool)
    run_id = await repo.create_run(scan_id="scan-tree", trigger_source="scheduled")
    await repo.bulk_insert(
        account_traces=[{"run_id": run_id, "account_id": "acc-1", "account_label": "Dad - Demo",
                         "execution_mode": "batch", "rescued_by_recheck": True,
                         "trades_executed": 3, "trades_failed": 0, "trades_skipped": 5,
                         "rules_created": [], "config_snapshot": {}}],
        lifecycle_events=[{"run_id": run_id, "account_id": "acc-1", "seq": 0,
                           "phase": "post_scan_recheck", "event_type": "state_reset", "detail": {}}],
        symbol_decisions=[{"run_id": run_id, "account_id": "acc-1", "phase": "post_scan_recheck",
                           "symbol": "B3USDT", "decision": "placed", "reason_code": "placed_ok",
                           "reason_detail": {}}],
        exchange_snapshots=[{"run_id": run_id, "account_id": "acc-1", "gate": "scan_start",
                             "positions": [], "position_count": 0, "wallet": {}}],
    )
    latest = await repo.get_latest_run_id_for_scan("scan-tree")
    assert latest == run_id
    tree = await repo.get_run_tree(run_id)
    assert tree["run"]["scan_id"] == "scan-tree"
    assert len(tree["accounts"]) == 1
    acct = tree["accounts"][0]
    assert acct["account_id"] == "acc-1"
    assert len(acct["lifecycle_events"]) == 1
    assert len(acct["symbol_decisions"]) == 1
    assert len(acct["exchange_snapshots"]) == 1
    assert "linked_trades" in acct
    assert "linked_close_rules" in acct
    assert "linked_close_executions" in acct


@pytest.mark.asyncio
async def test_list_runs_and_account_timeline(pool):
    repo = DebugTraceRepository(pool)
    r1 = await repo.create_run(scan_id="scan-x", trigger_source="scheduled")
    await repo.bulk_insert(account_traces=[{"run_id": r1, "account_id": "acc-9",
        "rules_created": [], "config_snapshot": {}}])
    runs = await repo.list_runs(limit=10, offset=0)
    assert any(r["id"] == r1 for r in runs["items"])
    tl = await repo.get_account_timeline("acc-9", limit=10)
    assert any(t["run_id"] == r1 for t in tl)
