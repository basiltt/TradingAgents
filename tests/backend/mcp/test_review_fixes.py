"""Review-fix regression tests — locks the gaps found in the final feature review.

Covers: live-protection wiring (breaker/leader/db_floor instantiated + sweep
gate), per-group service availability, scan_source validation, and the
backtest_only exchange-facing exclusion.
"""
from __future__ import annotations

import pytest

from backend.mcp.discovery import discover_tools

discover_tools()


# --- BE-F1: per-group service availability ---

def test_service_available_gates_on_real_backing_service():
    from types import SimpleNamespace

    from backend.mcp.core.registry import ToolGroup
    from backend.mcp.mount import MCPManager

    # app.state with only db → trades/accounts/optimizer unavailable
    app = SimpleNamespace(state=SimpleNamespace(db=object()))
    mgr = MCPManager(app)
    assert mgr._service_available(ToolGroup.SCANS) is True       # needs db ✓
    assert mgr._service_available(ToolGroup.PORTFOLIO) is True   # needs db ✓
    assert mgr._service_available(ToolGroup.TRADES) is False     # needs trade_repo
    assert mgr._service_available(ToolGroup.ACCOUNTS) is False   # needs accounts_service
    assert mgr._service_available(ToolGroup.OPTIMIZER) is False  # needs runner+sweep_repo

    # wire the services → now available
    app.state.trade_repo = object()
    app.state.accounts_service = object()
    app.state.mcp_backtest_runner = object()
    app.state.mcp_sweep_repo = object()
    assert mgr._service_available(ToolGroup.TRADES) is True
    assert mgr._service_available(ToolGroup.ACCOUNTS) is True
    assert mgr._service_available(ToolGroup.OPTIMIZER) is True


# --- F1/F4: protection objects + mcp_permitted gate ---

def test_manager_mcp_permitted_failsafe_when_no_breaker():
    from types import SimpleNamespace

    from backend.mcp.mount import MCPManager

    mgr = MCPManager(SimpleNamespace(state=SimpleNamespace()))
    # no breaker built yet → permitted (manager not enforcing) — fail-OPEN here is
    # acceptable because no sweep machinery is running; the breaker exists only
    # while enabled. The real gate is exercised once breaker is set:
    assert mgr.mcp_permitted() is True

    from backend.mcp.core.breaker import LiveSLIBreaker

    mgr.breaker = LiveSLIBreaker(trip_threshold=1, reset_threshold=1)
    mgr.breaker.observe(healthy=False)  # trip OPEN
    assert mgr.mcp_permitted() is False
    mgr.breaker.observe(healthy=True)   # reset
    assert mgr.mcp_permitted() is True


@pytest.mark.asyncio
async def test_await_breaker_clear_times_out_when_stuck_open():
    from backend.mcp.core.breaker import LiveSLIBreaker
    from backend.mcp.tools.optimizer.sweep_tools import _await_breaker_clear

    class _Mgr:
        def __init__(self):
            self.breaker = LiveSLIBreaker(trip_threshold=1, reset_threshold=99)
            self.breaker.observe(healthy=False)  # permanently open

        def mcp_permitted(self):
            return self.breaker.mcp_permitted()

    with pytest.raises(TimeoutError):
        await _await_breaker_clear(_Mgr(), max_wait_s=0.0)


# --- BE-F5: scan_source validation ---

def test_validate_scan_source_rejects_malformed():
    from backend.mcp.core.errors import MCPValidationError
    from backend.mcp.tools.optimizer.tools import _validate_scan_source

    _validate_scan_source(None)  # ok
    _validate_scan_source({})    # ok (date-range default)
    _validate_scan_source({"mode": "date_range"})  # ok
    with pytest.raises(MCPValidationError):
        _validate_scan_source({"mode": "schedule"})  # missing schedule_id
    with pytest.raises(MCPValidationError):
        _validate_scan_source({"mode": "explicit"})  # missing scan_ids
    with pytest.raises(MCPValidationError):
        _validate_scan_source({"mode": "bogus"})


# --- F8: backtest_only excludes exchange-facing cache_warmup ---

def test_backtest_only_preset_excludes_exchange_facing():
    from backend.mcp.core.registry import PRESETS, _REGISTRY

    warmup = _REGISTRY["cache_warmup"]
    assert warmup.exchange_facing is True
    assert PRESETS["backtest_only"](warmup) is False  # not auto-selected
    # but cache_status (read-only) IS selectable
    assert PRESETS["backtest_only"](_REGISTRY["cache_status"]) is True


# --- F1/F3/F4: protection mechanisms ACTUALLY instantiate at runtime ---

@pytest.mark.integration
@pytest.mark.asyncio
async def test_enable_wires_breaker_dbfloor_and_sli_task(mcp_pool):
    """The exact dead-code finding: after enable, the manager must have built a
    breaker + db_floor + SLI poll task (previously they existed only in tests)."""
    from fastapi import FastAPI

    from backend.mcp.mount import MCPManager, register_mcp

    class _DB:
        def __init__(self, pool):
            self.pool = pool

        async def list_scans(self):
            return []

    app = FastAPI()
    app.state.db = _DB(mcp_pool)
    register_mcp(app)
    mgr = MCPManager(app)
    app.state.mcp_manager = mgr
    await mgr.boot()
    await mgr.config_repo.set_token_hash("a" * 64)
    cfg = await mgr.config_repo.get()
    await mgr.config_repo.update({"enabled_groups": ["scans"]}, expected_row_version=cfg.row_version)
    try:
        await mgr.enable()
        # the protection objects are now LIVE, not dead code
        assert mgr.breaker is not None, "breaker not wired at runtime"
        assert mgr.db_floor is not None, "db_floor not wired at runtime"
        assert mgr._sli_task is not None and not mgr._sli_task.done(), "SLI poll task not running"
        assert app.state.mcp_db_floor is mgr.db_floor
        assert mgr.mcp_permitted() is True  # healthy at start
    finally:
        await mgr.shutdown()
        # teardown cancels the SLI task + clears protection
        assert mgr.breaker is None and mgr.db_floor is None


# === Iteration-2 review fixes ===

@pytest.mark.asyncio
async def test_optimize_config_uses_live_config_as_sweep_base(mcp_pool):
    """S2/BE2: when targeting a live schedule, the sweep base + uplift baseline
    must be the REAL live config, not the agent's `base` (so the human approves a
    config that was actually backtested against live)."""
    import json
    import uuid

    from backend.mcp.core.clock import RealClock
    from backend.mcp.core.dispatch import CallContext, dispatch
    from backend.mcp.core.registry import _REGISTRY

    # seed a live schedule with a distinctive config
    sid = "sched-" + uuid.uuid4().hex[:8]
    live = {"account_id": "acc1", "leverage": 7, "stop_loss_pct": 4.0,
            "take_profit_pct": 9.0, "capital_pct": 3.0, "direction": "straight",
            "starting_capital": 1000.0}
    async with mcp_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO scheduled_scans (id, name, schedule_type, schedule_config, "
            "scan_config, status, created_at, updated_at) "
            "VALUES ($1,'t','interval',$2::jsonb,$3::jsonb,'active',now(),now())",
            sid, json.dumps({"interval_minutes": 60}),
            json.dumps({"auto_trade_configs": [live]}),
        )

    seen_bases = []

    class _Runner:
        async def load_inputs(self, config):
            seen_bases.append(dict(config))  # the load_cfg carries base
            return ([{"scan_id": "s", "ticker": "BTCUSDT", "direction": "long", "score": 0.9}],
                    {"BTCUSDT": [{"open_time": 1, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 5}]},
                    {})

        async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
            seen_bases.append(dict(config))
            return {"net_profit_pct": float(config.get("leverage", 1)), "max_dd_pct": 8.0,
                    "sharpe": 1.0, "total_trades": 40, "top_trade_pnl_share": 0.2, "expectancy": 1.0}

    class _DB:
        def __init__(self, pool):
            self.pool = pool

        async def get_scheduled_scan(self, schedule_id):
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM scheduled_scans WHERE id=$1", schedule_id)
            return dict(row) if row else None

    class _State:
        def __init__(self, db, runner):
            self.db = db
            self.backtest_runner = runner
            self.mcp_manager = None

    class _Services:
        def __init__(self, db, runner):
            self._state = _State(db, runner)
            self.db = db
            self.backtest_runner = runner

    db = _DB(mcp_pool)
    runner = _Runner()
    ctx = CallContext(principal="t", session_id="s", tier="BACKTEST", correlation_id=None,
                      services=_Services(db, runner), clock=RealClock())
    # agent sends a WEAK base (leverage 1) to try to make the winner look good
    await dispatch(_REGISTRY["optimize_config"], {
        "space": {"leverage": [10, 20]}, "objective": "total_return", "strategy": "grid",
        "base": {"leverage": 1, "stop_loss_pct": 99.0},  # strawman
        "date_range_start": "2026-01-01", "date_range_end": "2026-02-01",
        "target_schedule_id": sid, "target_config_index": 0,
    }, ctx, audit=lambda x: None)

    # every base/combo the runner saw must carry the LIVE non-swept fields
    # (stop_loss_pct=4.0 from live, NOT 99.0 from the agent strawman)
    assert seen_bases, "runner never invoked"
    assert all(b.get("stop_loss_pct") == 4.0 for b in seen_bases if "stop_loss_pct" in b), \
        f"agent strawman leaked into the sweep: {[b.get('stop_loss_pct') for b in seen_bases]}"


def test_preflight_optimizer_on_by_intent_not_availability():
    """BE4: optimizer_on at preflight must reflect config intent even though the
    optimizer's backing service (sweep_repo) isn't wired until _start_transport."""
    from backend.mcp.core.registry import (
        MCPConfigView,
        ToolGroup,
        resolve_enabled,
    )

    # a config that enables optimizer via per-tool override (preset style)
    view = MCPConfigView(
        capability_tier="BACKTEST",
        enabled_groups=[],
        enabled_tools={"optimize_config": True, "sweep_run": True},
    )
    # availability=True (intent) → optimizer tools resolve
    resolved = resolve_enabled(view, available=lambda g: True, debug_allowed=False)
    assert any(s.group is ToolGroup.OPTIMIZER for s in resolved), \
        "optimizer intent not detected → SLI/shm preflight gate would be skipped"
