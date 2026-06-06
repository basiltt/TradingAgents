"""Unit tests for DebugTraceRecorder (no DB required — repository is mocked)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.debug_trace_recorder import DebugTraceRecorder


def _recorder(enabled=True, buffer_max=1000):
    repo = MagicMock()
    repo.create_run = AsyncMock(return_value=1)
    repo.finalize_run = AsyncMock()
    repo.bulk_insert = AsyncMock()
    repo.get_config = AsyncMock(return_value={
        "tracing_enabled": enabled, "retention_days": 60, "symbol_decision_cap": 200,
    })
    repo.delete_runs_older_than = AsyncMock(return_value=0)
    repo.recover_orphaned_runs = AsyncMock(return_value=0)
    rec = DebugTraceRecorder(repo, buffer_max=buffer_max)
    rec._enabled = enabled
    rec._symbol_decision_cap = 200
    return rec, repo


def test_emit_when_disabled_is_noop():
    rec, repo = _recorder(enabled=False)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    rec.emit_lifecycle(ctx, account_id="a1", phase="init_balances", event_type="marked_stopped")
    assert rec.buffered_count() == 0


def test_emit_lifecycle_buffers_event():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    rec.emit_lifecycle(ctx, account_id="a1", phase="init_balances", event_type="marked_stopped",
                       detail={"reason": "positions_already_open"})
    assert rec.buffered_count() == 1


def test_exchange_snapshot_sanitizes_wallet_to_allowlist():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    rec.emit_exchange_snapshot(
        ctx, account_id="a1", gate="scan_start",
        positions=[{"symbol": "AAPLUSDT", "size": "1"}],
        wallet={"totalEquity": "510", "totalAvailableBalance": "200",
                "apiKey": "SECRET", "some_other_field": "x"},
        equity=510.0,
    )
    snap = [e for e in rec.snapshot_buffer() if e["_table"] == "exchange_snapshots"][0]
    assert snap["wallet"] == {"totalEquity": "510", "totalAvailableBalance": "200"}
    assert "apiKey" not in snap["wallet"]


def test_exchange_snapshot_is_point_in_time_copy():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    live_positions = [{"symbol": "AAPLUSDT", "size": "1"}]
    rec.emit_exchange_snapshot(ctx, account_id="a1", gate="scan_start", positions=live_positions)
    live_positions.append({"symbol": "MUUSDT", "size": "2"})
    snap = [e for e in rec.snapshot_buffer() if e["_table"] == "exchange_snapshots"][0]
    assert snap["position_count"] == 1


def test_emit_never_raises_on_bad_input():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    rec.emit_symbol_decision(ctx, account_id=None, phase=None, symbol=None,
                             decision=None, reason_code=None, reason_detail=object())


def test_drop_on_pressure_increments_dropped():
    rec, repo = _recorder(buffer_max=2)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    for i in range(5):
        rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type=f"e{i}")
    assert rec.buffered_count() == 2
    assert ctx.dropped_event_count == 3


def test_symbol_decision_cap_truncates():
    rec, repo = _recorder()
    rec._symbol_decision_cap = 3
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1
    for i in range(10):
        rec.emit_symbol_decision(ctx, account_id="a1", phase="batch", symbol=f"S{i}USDT",
                                 decision="skipped", reason_code="min_score", reason_detail={})
    syms = [e for e in rec.snapshot_buffer() if e["_table"] == "symbol_decisions"]
    assert len(syms) == 4
    assert any(s["reason_code"] == "truncated" for s in syms)


@pytest.mark.asyncio
async def test_open_run_sets_run_id_and_persists():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    await rec.open_run(ctx, config_snapshot={"x": 1})
    assert ctx.run_id == 1
    repo.create_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_run_when_disabled_creates_no_run():
    """Kill-switch: a disabled recorder must NOT write even an empty run shell."""
    rec, repo = _recorder(enabled=False)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    await rec.open_run(ctx, config_snapshot={"num_configs": 1})
    assert ctx.run_id is None              # no run opened
    repo.create_run.assert_not_awaited()   # nothing persisted
    # close_run on a never-opened ctx is also a no-op (run_id is None).
    await rec.close_run(ctx, phase_reached="finalized")
    repo.finalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_flushes_buffer_to_repo():
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    ctx.run_id = 1
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    rec.emit_exchange_snapshot(ctx, account_id="a1", gate="scan_start", positions=[])
    await rec.drain_once()
    repo.bulk_insert.assert_awaited()
    assert rec.buffered_count() == 0


@pytest.mark.asyncio
async def test_drain_isolates_failing_table():
    """One table's bulk_insert failure must not discard the other tables' rows."""
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    ctx.run_id = 1
    inserted_tables = []
    async def _bulk(**kwargs):
        table = next(iter(kwargs))
        if table == "symbol_decisions":
            raise RuntimeError("poison")
        inserted_tables.append(table)
    repo.bulk_insert = AsyncMock(side_effect=_bulk)
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    rec.emit_symbol_decision(ctx, account_id="a1", phase="batch", symbol="FOO",
                             decision="skipped", reason_code="min_score", reason_detail={})
    rec.emit_exchange_snapshot(ctx, account_id="a1", gate="scan_start", positions=[])
    await rec.drain_once()
    assert "lifecycle_events" in inserted_tables
    assert "exchange_snapshots" in inserted_tables
    assert rec.buffered_count() == 0


@pytest.mark.asyncio
async def test_close_run_finalizes_with_dropped_count():
    rec, repo = _recorder(buffer_max=1)
    ctx = rec.new_run_context(scan_id="s1", trigger_source="manual")
    ctx.run_id = 1
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="a")
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="b")  # dropped
    await rec.close_run(ctx, phase_reached="finalized", total_symbols=10,
                        completed_symbols=10, failed_symbols=0, num_accounts=1)
    repo.finalize_run.assert_awaited_once()
    _, kwargs = repo.finalize_run.await_args
    assert kwargs["dropped_event_count"] == 1


@pytest.mark.asyncio
async def test_refresh_config_updates_enabled_flag():
    rec, repo = _recorder()
    repo.get_config = AsyncMock(return_value={
        "tracing_enabled": False, "retention_days": 30, "symbol_decision_cap": 99,
    })
    await rec.refresh_config()
    assert rec._enabled is False
    assert rec._retention_days == 30
    assert rec._symbol_decision_cap == 99


@pytest.mark.asyncio
async def test_start_recovers_orphaned_runs_then_shuts_down():
    rec, repo = _recorder()
    repo.recover_orphaned_runs = AsyncMock(return_value=3)
    await rec.start(drain_interval_s=999, cleanup_interval_s=999, initial_cleanup_delay_s=999)
    repo.recover_orphaned_runs.assert_awaited_once()
    assert rec._drain_lock is not None
    await rec.shutdown()


def test_emit_swallows_internal_exception(monkeypatch):
    """The fail-open contract: if anything inside emit raises, it must be swallowed
    (logged), never propagated to the trading path."""
    rec, repo = _recorder()
    ctx = rec.new_run_context(scan_id="s1", trigger_source="scheduled")
    ctx.run_id = 1

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rec, "_append", _boom)
    # None of these may raise:
    rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    rec.emit_symbol_decision(ctx, account_id="a1", phase="batch", symbol="FOO",
                             decision="skipped", reason_code="min_score", reason_detail={})
    rec.emit_exchange_snapshot(ctx, account_id="a1", gate="scan_start", positions=[])
    rec.emit_account_trace(ctx, account_id="a1", trades_executed=1)
    # Buffer stayed empty because _append always raised, but no exception escaped.
    assert rec.buffered_count() == 0
