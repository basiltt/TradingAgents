"""Performance gate for DebugTraceRecorder — the money path must never be slowed."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.debug_trace_recorder import DebugTraceRecorder


def _recorder(buffer_max=200000):
    repo = MagicMock()
    repo.bulk_insert = AsyncMock()
    rec = DebugTraceRecorder(repo, buffer_max=buffer_max)
    rec._enabled = True
    rec._symbol_decision_cap = 1000000  # don't truncate during perf test
    return rec


def test_emit_overhead_is_sub_microsecond():
    """Each enabled emit must be cheap (< ~5 microseconds average)."""
    rec = _recorder()
    ctx = rec.new_run_context(scan_id="s1")
    ctx.run_id = 1
    N = 50000
    start = time.perf_counter()
    for i in range(N):
        rec.emit_symbol_decision(ctx, account_id="a1", phase="batch", symbol="FOO",
                                 decision="skipped", reason_code="min_score", reason_detail={})
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / N) * 1_000_000
    assert per_call_us < 5.0, f"emit too slow: {per_call_us:.3f} us/call"


def test_emit_when_disabled_is_effectively_free():
    rec = _recorder()
    rec._enabled = False
    ctx = rec.new_run_context(scan_id="s1")
    ctx.run_id = 1
    N = 100000
    start = time.perf_counter()
    for i in range(N):
        rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / N) * 1_000_000
    assert per_call_us < 1.0, f"disabled emit too slow: {per_call_us:.3f} us/call"
    assert rec.buffered_count() == 0


@pytest.mark.asyncio
async def test_trading_unblocked_when_drainer_stalled():
    """Simulate a hung drainer: emits must still return instantly and drop on overflow."""
    rec = _recorder(buffer_max=100)
    hang = asyncio.Event()
    async def _hang(**kwargs):
        await hang.wait()
    rec._repo.bulk_insert = AsyncMock(side_effect=_hang)
    ctx = rec.new_run_context(scan_id="s1")
    ctx.run_id = 1
    start = time.perf_counter()
    for i in range(10000):
        rec.emit_lifecycle(ctx, account_id="a1", phase="batch", event_type="x")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"emits blocked: {elapsed:.3f}s"
    assert rec.buffered_count() == 100
    assert ctx.dropped_event_count == 9900
    hang.set()


@pytest.mark.asyncio
async def test_try_trade_timing_parity_on_vs_off():
    """Batch _try_trade timing with tracing ON must be within tolerance of OFF."""
    from backend.services.auto_trade_service import AutoTradeExecutor, _AccountState

    def make_executor(with_recorder):
        rec = _recorder() if with_recorder else None
        ctx = rec.new_run_context(scan_id="s1") if rec else None
        if ctx:
            ctx.run_id = 1
        accounts = AsyncMock()
        return AutoTradeExecutor(accounts, None, recorder=rec, debug_ctx=ctx)

    async def run(executor, n):
        state = _AccountState(config={"account_id": "a", "min_score": 9,
                                      "confidence_filter": "any", "execution_mode": "batch"})
        state.base_capital = 1000.0
        result = {"status": "completed", "ticker": "FOO", "direction": "sell",
                  "confidence": "high", "score": -3}  # always skipped at min_score
        start = time.perf_counter()
        for _ in range(n):
            await executor._try_trade(state, result, phase="batch")
        return time.perf_counter() - start

    N = 20000
    off = await run(make_executor(False), N)
    on = await run(make_executor(True), N)
    assert on < off + 0.5, f"tracing added too much: on={on:.3f}s off={off:.3f}s"
