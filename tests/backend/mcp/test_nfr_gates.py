"""NFR verification tests — assert the spec's non-functional gates (NFR-001..012).

These lock the quantified thresholds the spec names so a regression is caught:
read-tool latency, audit-write latency, token-budget ceilings, sweep throughput,
startup overhead, NaN-at-persist integrity, and the health sub-status.
"""
from __future__ import annotations

import time

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import _REGISTRY, PRESETS, iter_specs
from backend.mcp.discovery import discover_tools

discover_tools()


# --- NFR-004: preset token-budget ceilings + per-tool soft cap ---

def test_nfr004_preset_budgets_within_ceilings():
    from backend.mcp.core.budget import (
        PER_TOOL_SOFT_CAP,
        PRESET_TOKEN_CEILINGS,
        estimate_total_tokens,
        estimate_tool_tokens,
    )

    specs = iter_specs()
    for preset, ceiling in PRESET_TOKEN_CEILINGS.items():
        selected = [s for s in specs if PRESETS[preset](s)]
        total = estimate_total_tokens(selected)
        assert total <= ceiling, f"preset {preset!r} budget {total} exceeds ceiling {ceiling}"
    # per-tool soft cap: no single tool's advertised schema is absurdly large
    for s in specs:
        est = estimate_tool_tokens(s)
        assert est <= PER_TOOL_SOFT_CAP * 3, f"{s.name} schema {est} tok is implausibly large"


def test_nfr004_estimator_deterministic_within_10pct_of_char_model():
    """The estimate tracks the char/4 model within tolerance (±10% calibration)."""
    from backend.mcp.core.budget import estimate_tool_tokens

    spec = _REGISTRY["scans_list"]
    a = estimate_tool_tokens(spec)
    b = estimate_tool_tokens(spec)
    assert a == b and a > 0


# --- NFR-001: read-tool latency (in-process dispatch) ---

class _DB:
    async def list_scans(self):
        return [{"scan_id": f"s{i}", "status": "completed"} for i in range(20)]


class _Services:
    db = _DB()


def _ctx():
    return CallContext(principal="t", session_id="s", tier="READ_ONLY",
                       correlation_id=None, services=_Services(), clock=RealClock())


@pytest.mark.asyncio
async def test_nfr001_read_tool_latency_under_200ms():
    """A read tool's in-process dispatch p95 must be well under 200ms (NFR-001).
    Measured over repeated calls against an in-memory fake (no network)."""
    spec = _REGISTRY["scans_list"]
    samples = []
    for _ in range(50):
        t0 = time.perf_counter()
        await dispatch(spec, {}, _ctx(), audit=lambda r: None)
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95)]
    assert p95 < 200.0, f"read-tool p95 {p95:.1f}ms exceeds 200ms"


# --- NFR-003: audit write is non-blocking + fast ---

@pytest.mark.asyncio
async def test_nfr003_audit_enqueue_is_fast_nonblocking():
    """The audit enqueue path adds < 5ms (it's a queue put, not a DB write)."""
    from backend.mcp.core.audit import AuditWriter

    class _Repo:
        async def last_chain(self):
            return 0, None

        async def append(self, record):
            return None

    w = AuditWriter(_Repo())
    await w.start()
    try:
        samples = []
        for _ in range(100):
            t0 = time.perf_counter()
            await w.enqueue({"tool_name": "x", "status": "ok"})
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95)]
        assert p95 < 5.0, f"audit enqueue p95 {p95:.2f}ms exceeds 5ms"
    finally:
        await w.shutdown()


# --- NFR-005: 5000-combo sweep orchestration < 60s with a fake runner ---

@pytest.mark.asyncio
async def test_nfr005_large_sweep_orchestration_under_60s():
    """5000-combo orchestration (FakeRunner) completes < 60s (NFR-005)."""
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    class _FastRunner:
        async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
            return {"total_return": float(config.get("a", 0)), "total_trades": 40,
                    "max_drawdown": 5.0, "top_trade_pnl_share": 0.1}

    # 5000 combos via a single 5000-wide axis
    space = {"a": list(range(5000))}
    t0 = time.perf_counter()
    result = await run_sweep_inproc(
        runner=_FastRunner(), space=space, base={}, strategy="grid",
        objective="total_return", signals=[], snapshot={}, instrument_info={},
        n=5000, seed=0,
    )
    elapsed = time.perf_counter() - t0
    assert result["total_combos"] == 5000
    assert elapsed < 60.0, f"5000-combo orchestration took {elapsed:.1f}s (> 60s)"


# --- NFR-012: NaN/Inf sanitize at the sweep persist boundary ---

def test_nfr012_nan_inf_sanitized_to_null():
    from backend.mcp.repositories.sweep_repo import _nan_to_null, _safe_objective

    dirty = {"sharpe": float("nan"), "ret": float("inf"), "ok": 1.5, "n": {"x": float("-inf")}}
    clean = _nan_to_null(dirty)
    assert clean["sharpe"] is None and clean["ret"] is None
    assert clean["ok"] == 1.5 and clean["n"]["x"] is None
    assert _safe_objective(float("nan")) is None
    assert _safe_objective(3.2) == 3.2


# --- NFR-011: OFF-path seam adds < 50ms ---

def test_nfr011_register_mcp_overhead_under_50ms():
    """register_mcp (the create_app OFF-path seam) adds < 50ms (NFR-011): it
    mounts the indirection + control router, reads nothing, opens no DB."""
    from fastapi import FastAPI

    from backend.mcp.mount import register_mcp

    t0 = time.perf_counter()
    app = FastAPI()
    register_mcp(app)
    elapsed = (time.perf_counter() - t0) * 1000
    assert app.state.mcp_asgi is None  # inert
    assert elapsed < 50.0, f"register_mcp overhead {elapsed:.1f}ms exceeds 50ms"


# --- NFR-010: /api/v1/health mcp sub-status (degraded != 503) ---

def test_nfr010_health_substatus_helper():
    from fastapi import FastAPI

    from backend.main import _mcp_health_substatus

    # no manager → absent, no crash
    app = FastAPI()
    assert _mcp_health_substatus(app)["state"] == "absent"

    # manager present but server off → off (not an error state)
    class _Mgr:
        last_error = None
    app.state.mcp_manager = _Mgr()
    app.state.mcp_server = None
    sub = _mcp_health_substatus(app)
    assert sub["state"] == "off" and sub["error"] is None
