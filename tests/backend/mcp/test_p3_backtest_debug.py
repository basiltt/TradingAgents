"""P3 backtest + debug tool tests — AC-016, AC-018."""
from __future__ import annotations

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import MCPConfigView, _REGISTRY, resolve_enabled
from backend.mcp.discovery import discover_tools

discover_tools()


class _Services:
    def __init__(self, *, backtest_service=None, debug_trace_recorder=None):
        self.backtest_service = backtest_service
        self.debug_trace_recorder = debug_trace_recorder
        self.db = None


def _ctx(**svc):
    return CallContext(principal="t", session_id="s", tier="BACKTEST",
                       correlation_id=None, services=_Services(**svc), clock=RealClock())


class _FakeBacktestService:
    def __init__(self):
        self.created = []

    async def create_backtest(self, config, client_id="x"):
        self.created.append((config, client_id))
        return "run-123"

    async def get_backtest(self, run_id):
        return {"id": run_id, "status": "completed", "results": {"metrics": {}}}

    async def list_backtests(self, filters):
        return [{"id": "r1", "status": "completed"}]

    async def compare_backtests(self, run_ids):
        return {"runs": [{"id": rid} for rid in run_ids]}


# --- AC-016: backtest tools ---

def test_backtest_tools_registered():
    for n in ("backtest_run", "backtest_get", "backtest_list", "backtest_compare"):
        assert n in _REGISTRY


def test_backtest_run_schema_equals_backtest_create_request():
    """Schema-equivalence: the advertised input schema IS BacktestCreateRequest."""
    from backend.schemas.backtest_schemas import BacktestCreateRequest

    spec = _REGISTRY["backtest_run"]
    assert spec.input_schema is BacktestCreateRequest
    assert spec.input_schema.model_json_schema() == BacktestCreateRequest.model_json_schema()


@pytest.mark.asyncio
async def test_backtest_run_creates_and_returns_run_id():
    svc = _FakeBacktestService()
    spec = _REGISTRY["backtest_run"]
    valid = {
        "starting_capital": 1000.0,
        "date_range_start": "2026-01-01T00:00:00+00:00",
        "date_range_end": "2026-01-05T00:00:00+00:00",
        "scan_source": {"mode": "date_range"},
    }
    result = await dispatch(spec, valid, _ctx(backtest_service=svc), audit=lambda r: None)
    assert result["isError"] is False, result
    assert result["structuredContent"]["run_id"] == "run-123"
    assert svc.created and svc.created[0][1].startswith("mcp:")


@pytest.mark.asyncio
async def test_backtest_get_list_compare():
    svc = _FakeBacktestService()
    rget = await dispatch(_REGISTRY["backtest_get"], {"run_id": "r1"}, _ctx(backtest_service=svc), audit=lambda r: None)
    assert rget["structuredContent"]["run"]["status"] == "completed"
    rlist = await dispatch(_REGISTRY["backtest_list"], {"limit": 10}, _ctx(backtest_service=svc), audit=lambda r: None)
    assert rlist["structuredContent"]["count"] == 1
    rcmp = await dispatch(_REGISTRY["backtest_compare"], {"run_ids": ["a", "b"]}, _ctx(backtest_service=svc), audit=lambda r: None)
    assert len(rcmp["structuredContent"]["comparison"]["runs"]) == 2


@pytest.mark.asyncio
async def test_backtest_run_service_unavailable():
    spec = _REGISTRY["backtest_run"]
    valid = {
        "starting_capital": 1000.0,
        "date_range_start": "2026-01-01T00:00:00+00:00",
        "date_range_end": "2026-01-05T00:00:00+00:00",
        "scan_source": {"mode": "date_range"},
    }
    result = await dispatch(spec, valid, _ctx(backtest_service=None), audit=lambda r: None)
    assert result["isError"] is True


# --- AC-018: debug gate ---

def test_debug_tools_hidden_unless_allow_debug():
    cfg = MCPConfigView(capability_tier="READ_ONLY", enabled_groups=["debug"], enabled_tools={})
    # allow_debug False -> debug tools NOT advertised
    names_off = {s.name for s in resolve_enabled(cfg, available=lambda g: True, debug_allowed=False)}
    assert "debug_scan_trace" not in names_off
    # allow_debug True -> advertised
    names_on = {s.name for s in resolve_enabled(cfg, available=lambda g: True, debug_allowed=True)}
    assert "debug_scan_trace" in names_on


@pytest.mark.asyncio
async def test_debug_scan_trace_redacts_and_caps():
    class _Repo:
        async def get_latest_run_id_for_scan(self, scan_id):
            return 7

        async def get_run_tree(self, rid):
            return {"run": {"id": rid}, "api_key_encrypted": "SECRET", "accounts": [{"x": 1}]}

    class _Recorder:
        repo = _Repo()

    spec = _REGISTRY["debug_scan_trace"]
    ctx = CallContext(principal="t", session_id="s", tier="READ_ONLY", correlation_id=None,
                      services=_Services(debug_trace_recorder=_Recorder()), clock=RealClock())
    result = await dispatch(spec, {"scan_id": "s1"}, ctx, audit=lambda r: None)
    assert result["isError"] is False
    tree = result["structuredContent"]["tree"]
    assert "api_key_encrypted" not in tree
    assert "SECRET" not in str(tree)


@pytest.mark.asyncio
async def test_debug_unavailable_when_no_recorder():
    spec = _REGISTRY["debug_scan_trace"]
    ctx = CallContext(principal="t", session_id="s", tier="READ_ONLY", correlation_id=None,
                      services=_Services(debug_trace_recorder=None), clock=RealClock())
    result = await dispatch(spec, {"scan_id": "s1"}, ctx, audit=lambda r: None)
    assert result["isError"] is True
