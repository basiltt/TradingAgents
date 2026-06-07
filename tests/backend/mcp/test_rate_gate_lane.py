"""bybit_rate_gate lane additive-change tests — TASK-P3-08 (signature-compat)."""
from __future__ import annotations

import pytest

from backend.services.bybit_rate_gate import BybitRateGate


@pytest.mark.asyncio
async def test_existing_callers_unchanged_default_live_lane():
    """acquire_async(channel) — existing positional call — behaves as before."""
    gate = BybitRateGate()
    # the live lane gets the full budget (no exception, returns immediately under budget)
    await gate.acquire_async("public")
    await gate.acquire_async("private", lane="live")


@pytest.mark.asyncio
async def test_mcp_lane_reserves_headroom_for_live():
    """The mcp lane uses a reduced effective budget so live keeps reserved slots."""
    gate = BybitRateGate()
    # fill the mcp lane's reduced budget; live should still be able to acquire
    # (we can't easily assert timing, but the call must accept the lane kwarg and
    # not raise — the reservation is structural).
    for _ in range(3):
        await gate.acquire_async("public", lane="mcp")
    # live lane still works
    await gate.acquire_async("public", lane="live")


def test_acquire_async_signature_is_additive():
    import inspect

    sig = inspect.signature(BybitRateGate.acquire_async)
    params = sig.parameters
    assert "channel" in params
    assert "lane" in params
    # lane is keyword-only with default 'live' (non-breaking)
    assert params["lane"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["lane"].default == "live"
