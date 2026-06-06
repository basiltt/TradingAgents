"""End-to-end: recorder + repository produce a full forensic tree for a rescue scenario."""

import os
import asyncpg
import pytest
import pytest_asyncio

from backend.services.debug_trace_repository import DebugTraceRepository
from backend.services.debug_trace_recorder import DebugTraceRecorder

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
                await conn.execute("UPDATE schema_version SET version=$1", ver)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM debug_runs")
        await conn.execute(
            "UPDATE debug_config SET tracing_enabled=TRUE, retention_days=60, "
            "symbol_decision_cap=200, updated_at=now() WHERE id=1"
        )
    await p.close()


@pytest.mark.asyncio
async def test_rescue_scenario_full_tree(pool):
    repo = DebugTraceRepository(pool)
    rec = DebugTraceRecorder(repo)
    rec._enabled = True
    rec._symbol_decision_cap = 200

    ctx = rec.new_run_context(scan_id="scan-rescue", trigger_source="scheduled", schedule_id="sch-1")
    await rec.open_run(ctx, config_snapshot={"num_configs": 1})

    rec.emit_exchange_snapshot(ctx, account_id="dad", gate="scan_start",
                               positions=[{"symbol": "AAPLUSDT", "size": "1"},
                                          {"symbol": "NOKIAUSDT", "size": "1"},
                                          {"symbol": "BARDUSDT", "size": "1"}],
                               wallet={"totalEquity": "500"}, equity=500.0)
    rec.emit_lifecycle(ctx, account_id="dad", phase="init_balances",
                       event_type="marked_stopped", detail={"reason": "positions_already_open"})

    rec.emit_exchange_snapshot(ctx, account_id="dad", gate="recheck", positions=[],
                               wallet={"totalEquity": "508"}, equity=508.0)
    rec.emit_lifecycle(ctx, account_id="dad", phase="post_scan_recheck", event_type="recheck_entered")
    rec.emit_lifecycle(ctx, account_id="dad", phase="post_scan_recheck", event_type="state_reset")
    for sym in ("B3USDT", "MUUSDT", "IBMUSDT"):
        rec.emit_symbol_decision(ctx, account_id="dad", phase="post_scan_recheck", symbol=sym,
                                 decision="placed", reason_code="placed_ok", reason_detail={},
                                 scan_score=-7, scan_confidence="high", scan_direction="sell",
                                 order_id=f"ord-{sym}")
    rec.emit_account_trace(ctx, account_id="dad", account_label="Dad - Demo",
                           execution_mode="batch", final_stopped_reason=None,
                           rescued_by_recheck=True, trades_executed=3, trades_skipped=0,
                           rules_created=[], config_snapshot={})

    await rec.close_run(ctx, phase_reached="finalized", total_symbols=580,
                        completed_symbols=580, failed_symbols=0, num_accounts=1)

    run_id = await repo.get_latest_run_id_for_scan("scan-rescue")
    tree = await repo.get_run_tree(run_id)
    assert tree["run"]["num_accounts"] == 1
    acct = tree["accounts"][0]
    assert acct["account_label"] == "Dad - Demo"
    assert acct["rescued_by_recheck"] is True
    assert len(acct["exchange_snapshots"]) == 2
    gates = {s["gate"] for s in acct["exchange_snapshots"]}
    assert gates == {"scan_start", "recheck"}
    placed = [d for d in acct["symbol_decisions"] if d["decision"] == "placed"]
    assert len(placed) == 3
    assert "rescued by post-scan recheck" in acct["narrative"]
    assert "placed 3 trade" in acct["narrative"]
