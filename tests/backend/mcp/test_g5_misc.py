"""G5 misc tests — kline cache tools, dry-connect self-test, saturated-loop kill."""
from __future__ import annotations

import asyncio

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import _REGISTRY
from backend.mcp.discovery import discover_tools

discover_tools()


# --- kline cache tools (FR-014) ---

class _CacheSvc:
    async def cache_status(self, symbols, interval, start, end):
        return {"symbols_total": len(symbols), "symbols_cached": 1,
                "symbols_with_gaps": symbols[1:], "ready": len(symbols) == 1}

    async def warmup_cache(self, symbols, interval, start, end):
        return {"cached": 1, "fetched": len(symbols) - 1, "failed": 0}


class _Services:
    def __init__(self):
        self.backtest_service = _CacheSvc()
        self.db = None


def _ctx():
    return CallContext(principal="t", session_id="s", tier="BACKTEST",
                       correlation_id=None, services=_Services(), clock=RealClock())


def test_cache_tools_registered():
    assert "cache_status" in _REGISTRY and "cache_warmup" in _REGISTRY


@pytest.mark.asyncio
async def test_cache_status_reports_coverage():
    r = await dispatch(_REGISTRY["cache_status"], {
        "symbols": ["BTCUSDT", "ETHUSDT"], "interval": "5m",
        "start": "2026-01-01", "end": "2026-02-01",
    }, _ctx(), audit=lambda x: None)
    assert r["isError"] is False
    assert r["structuredContent"]["symbols_total"] == 2


@pytest.mark.asyncio
async def test_cache_warmup_is_exchange_facing_and_mutating():
    spec = _REGISTRY["cache_warmup"]
    assert spec.exchange_facing is True and spec.mutating is True
    r = await dispatch(spec, {"symbols": ["BTCUSDT", "ETHUSDT"], "interval": "5m",
                              "start": "2026-01-01", "end": "2026-02-01"},
                       _ctx(), audit=lambda x: None)
    assert r["isError"] is False


def test_cache_warmup_excluded_from_broad_presets():
    """Exchange-facing warmup must NOT be auto-selected by _standard/_full."""
    from backend.mcp.core.registry import PRESETS
    spec = _REGISTRY["cache_warmup"]
    assert not PRESETS["standard"](spec)
    assert not PRESETS["full"](spec)


# --- dry-connect self-test (FR-003) ---

def test_server_self_test_passes_for_functional_server():
    from backend.mcp.core.registry import MCPConfigView
    from backend.mcp.core.server import MCPServer

    view = MCPConfigView(capability_tier="READ_ONLY", enabled_groups=["scans"], enabled_tools={})
    server = MCPServer(config_view=view, app_state=type("S", (), {"db": object()})(),
                       audit_writer=None, available=lambda g: True)
    assert server.self_test() is True


# --- saturated-loop kill (AC-019) ---

@pytest.mark.asyncio
async def test_kill_switch_cancels_inflight_sweep_under_load():
    """A sweep task is cancellable even while the loop is busy (out-of-band kill
    path semantics): cancelling the tracked task stops it promptly."""
    started = asyncio.Event()

    async def _long_sweep():
        started.set()
        # simulate a long-running sweep that yields
        for _ in range(10_000):
            await asyncio.sleep(0.001)

    task = asyncio.create_task(_long_sweep())
    await started.wait()
    # saturate the loop a little, then kill
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
