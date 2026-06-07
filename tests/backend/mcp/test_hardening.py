"""Hardening tests — the gaps found by the adversarial review."""
from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from backend.mcp.core.audit import AuditWriter
from backend.mcp.core.clock import FakeClock, RealClock
from backend.mcp.core.dispatch import CallContext, _deep_redact, dispatch
from backend.mcp.core.redact import redact_record
from backend.mcp.core.registry import SafetyClass, ToolGroup, ToolSpec


class _In(BaseModel):
    x: int = 0


class _Out(BaseModel):
    y: int = 0


def _spec(handler, *, name="t_tool", group=ToolGroup.SCANS, sc=SafetyClass.READ_ONLY, mutating=False):
    return ToolSpec(name=name, group=group, handler=handler, input_schema=_In,
                    output_schema=_Out, safety_class=sc, mutating=mutating,
                    exchange_facing=False, description="d")


def _ctx(tier="READ_ONLY", clock=None):
    return CallContext(principal="tok", session_id="s", tier=tier, correlation_id=None,
                       services=object(), clock=clock or RealClock())


# --- redaction depth + aliases (security-H-F3/H-F4) ---

def test_redact_recurses_into_nested_dicts():
    rec = {"meta": {"api_key": "SECRET", "equity": 100.0, "bybit_uid": "9"}, "id": "a"}
    out = redact_record(rec)
    assert "api_key" not in out["meta"]
    assert out["meta"]["equity"] == "redacted"
    assert "bybit_uid" not in out["meta"]
    assert out["id"] == "a"


def test_redact_money_alias_keys():
    rec = {"total_equity": 1.0, "net_pnl": 2.0, "usdt_balance": 3.0, "margin_used": 4.0}
    out = redact_record(rec)
    assert all(out[k] == "redacted" for k in rec)


def test_redact_recurses_into_list_of_dicts():
    rec = {"positions": [{"symbol": "BTC", "unrealized_pnl": 5.0, "api_secret": "X"}]}
    out = redact_record(rec)
    assert out["positions"][0]["unrealized_pnl"] == "redacted"
    assert "api_secret" not in out["positions"][0]


def test_deep_redact_backstop_strips_secret_at_depth():
    obj = {"a": {"b": {"access_token": "LEAK"}}}
    out = _deep_redact(obj)
    assert "LEAK" not in str(out)


# --- dispatch: central redaction backstop (security-H-F2) ---

@pytest.mark.asyncio
async def test_dispatch_backstop_redacts_forgotten_secret():
    class _Leaky(BaseModel):
        api_key: str = "SECRET"
        ok: int = 1

    async def handler(args, ctx):
        return _Leaky()

    spec = ToolSpec(name="leaky_tool", group=ToolGroup.SCANS, handler=handler,
                    input_schema=_In, output_schema=_Leaky, safety_class=SafetyClass.READ_ONLY,
                    mutating=False, exchange_facing=False, description="d")
    result = await dispatch(spec, {}, _ctx(), audit=lambda r: None)
    assert "SECRET" not in str(result["structuredContent"])
    assert "api_key" not in result["structuredContent"]


# --- dispatch: timeout (QA-H-F4) ---

@pytest.mark.asyncio
async def test_dispatch_timeout():
    async def slow(args, ctx):
        await asyncio.sleep(10)
        return _Out()

    audited = []
    result = await dispatch(_spec(slow), {}, _ctx(), audit=audited.append, timeout_s=0.01)
    assert result["isError"] is True
    assert "timeout" in result["content"][0]["text"].lower()
    assert audited[0]["status"] == "timeout"


# --- dispatch: CancelledError propagates (security-H-F10/backend-H-F3) ---

@pytest.mark.asyncio
async def test_dispatch_propagates_cancellation():
    async def cancels(args, ctx):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await dispatch(_spec(cancels), {}, _ctx(), audit=lambda r: None)


# --- dispatch: LIVE_MONEY denied at BACKTEST tier, handler never called (QA-H-F10) ---

@pytest.mark.asyncio
async def test_dispatch_live_money_denied_handler_not_invoked():
    called = {"n": 0}

    async def live(args, ctx):
        called["n"] += 1
        return _Out()

    spec = _spec(live, name="live_tool", group=ToolGroup.TRADES, sc=SafetyClass.LIVE_MONEY, mutating=True)
    audited = []
    result = await dispatch(spec, {}, _ctx(tier="BACKTEST"), audit=audited.append)
    assert result["isError"] is True
    assert called["n"] == 0  # handler never ran
    assert audited[0]["status"] == "rejected"


# --- dispatch: args are redacted in the audit record (security-H-F6) ---

@pytest.mark.asyncio
async def test_dispatch_audit_args_redacted():
    async def handler(args, ctx):
        return _Out()

    class _SecretIn(BaseModel):
        api_key: str = "x"
        limit: int = 5

    spec = ToolSpec(name="sec_tool", group=ToolGroup.SCANS, handler=handler,
                    input_schema=_SecretIn, output_schema=_Out, safety_class=SafetyClass.READ_ONLY,
                    mutating=False, exchange_facing=False, description="d")
    audited = []
    await dispatch(spec, {"api_key": "SECRET", "limit": 5}, _ctx(), audit=audited.append)
    assert "SECRET" not in str(audited[0]["args_redacted"])
    assert audited[0]["args_redacted"].get("limit") == 5


# --- audit: concurrent enqueues never fork the chain (QA-H-F3) ---

@pytest.mark.asyncio
async def test_audit_concurrent_enqueue_no_fork():
    persisted = []

    class _Repo:
        async def last_chain(self):
            return (0, None)

        async def append(self, record):
            persisted.append(record)

    writer = AuditWriter(_Repo())
    await writer.start()
    try:
        await asyncio.gather(*[writer.enqueue({"tool_name": f"t{i}", "status": "ok"}) for i in range(200)])
        await writer.drain()
    finally:
        await writer.shutdown()
    seqs = [r["seq"] for r in persisted]
    assert sorted(seqs) == list(range(1, 201))  # contiguous, no dupes
    # every prev_hash links to the previous entry_hash
    by_seq = {r["seq"]: r for r in persisted}
    for i in range(2, 201):
        assert by_seq[i]["prev_hash"] == by_seq[i - 1]["entry_hash"]


# --- audit: queue-full sync fallback still chains (QA-H-F3) ---

@pytest.mark.asyncio
async def test_audit_queue_full_fallback_chains():
    persisted = []

    class _Repo:
        async def last_chain(self):
            return (0, None)

        async def append(self, record):
            persisted.append(record)

    writer = AuditWriter(_Repo(), maxsize=1)
    await writer.start()
    try:
        # burst more than maxsize to exercise the synchronous fallback
        for i in range(10):
            await writer.enqueue({"tool_name": f"t{i}", "status": "ok"})
        await writer.drain()
    finally:
        await writer.shutdown()
    seqs = sorted(r["seq"] for r in persisted)
    assert seqs == list(range(1, 11))


# --- apply: SL=None breaches the ceiling (security-H-F7) ---

def test_sanity_ceiling_rejects_missing_stop_loss():
    from backend.mcp.tools.optimizer.apply import sanity_ceiling_ok

    assert not sanity_ceiling_ok({"leverage": 10, "capital_pct": 5.0})  # no SL
    assert not sanity_ceiling_ok({"leverage": 10, "stop_loss_pct": None, "capital_pct": 5.0})
    assert sanity_ceiling_ok({"leverage": 10, "stop_loss_pct": 100.0, "capital_pct": 5.0})


def test_sanity_ceiling_capital_and_leverage_bounds():
    from backend.mcp.tools.optimizer.apply import sanity_ceiling_ok

    assert not sanity_ceiling_ok({"leverage": 10, "stop_loss_pct": 100, "capital_pct": 100})  # capital > max
    assert sanity_ceiling_ok({"leverage": 50, "stop_loss_pct": 100, "capital_pct": 50})  # boundary ok
    assert not sanity_ceiling_ok({"leverage": 51, "stop_loss_pct": 100, "capital_pct": 5})  # over max lev


# --- orchestrator: all-excluded -> keep_current True (backend-H-F5/QA-H-F8) ---

@pytest.mark.asyncio
async def test_orchestrator_all_excluded_keeps_current():
    from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc

    class _Runner:
        async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
            return {"sharpe": 5.0, "total_trades": 1, "max_drawdown": 10.0}  # too few trades

    result = await run_sweep_inproc(
        runner=_Runner(), space={"leverage": [5, 10]}, base={}, strategy="grid",
        objective="sharpe", constraints={"min_trades": 30}, signals=[], snapshot={},
        instrument_info={},
    )
    assert result["ranked"] == []
    assert result["keep_current"] is True
    assert result["winner"] is None
