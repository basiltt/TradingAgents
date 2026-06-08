"""Transport wiring + auth/host guard tests — TASK-P0-05 (transport)."""
from __future__ import annotations

import pytest

from backend.mcp.core.auth import BearerAuthenticator, generate_token
from backend.mcp.core.transport import _AuthHostGuard


class _Captured:
    def __init__(self):
        self.status = None
        self.body = b""

    async def send(self, msg):
        if msg["type"] == "http.response.start":
            self.status = msg["status"]
        elif msg["type"] == "http.response.body":
            self.body += msg.get("body", b"")


async def _noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _scope(headers):
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp/rpc",
        "headers": [[k.encode(), v.encode()] for k, v in headers.items()],
    }


async def _inner(scope, receive, send):
    # the "real" transport — only reached if the guard passes
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"OK"})


@pytest.mark.asyncio
async def test_guard_rejects_missing_token():
    plaintext, token_hash = generate_token()
    guard = _AuthHostGuard(_inner, BearerAuthenticator(token_hash))
    cap = _Captured()
    await guard(_scope({"host": "127.0.0.1:8000"}), _noop_receive, cap.send)
    assert cap.status == 401


@pytest.mark.asyncio
async def test_guard_rejects_bad_host():
    plaintext, token_hash = generate_token()
    guard = _AuthHostGuard(_inner, BearerAuthenticator(token_hash))
    cap = _Captured()
    await guard(
        _scope({"host": "attacker.com", "authorization": f"Bearer {plaintext}"}),
        _noop_receive, cap.send,
    )
    assert cap.status == 403


@pytest.mark.asyncio
async def test_guard_allows_valid_token_loopback():
    plaintext, token_hash = generate_token()
    guard = _AuthHostGuard(_inner, BearerAuthenticator(token_hash))
    cap = _Captured()
    await guard(
        _scope({"host": "127.0.0.1:8000", "authorization": f"Bearer {plaintext}"}),
        _noop_receive, cap.send,
    )
    assert cap.status == 200
    assert cap.body == b"OK"


@pytest.mark.asyncio
async def test_guard_rejects_non_loopback_origin():
    plaintext, token_hash = generate_token()
    guard = _AuthHostGuard(_inner, BearerAuthenticator(token_hash))
    cap = _Captured()
    await guard(
        _scope({"host": "127.0.0.1:8000", "origin": "https://evil.com",
                "authorization": f"Bearer {plaintext}"}),
        _noop_receive, cap.send,
    )
    assert cap.status == 403


# --- delegate schema fidelity (the **kwargs double-wrap regression) -------------------
#
# FastMCP derives each tool's advertised inputSchema by INTROSPECTING the delegate's
# signature. A delegate declared as `async def _delegate(**kwargs)` collapses to a
# single `kwargs` property, so every parameterized tool (trades_get, backtest_get,
# optimize_config, ...) becomes uncallable over HTTP — the client cannot send the
# real fields. The delegate must therefore carry a real __signature__ mirroring the
# tool's input_schema, while still forwarding a FLAT dict to MCPServer.call_tool
# (dispatch validates raw args via spec.input_schema(**raw_args)).

from pydantic import BaseModel, Field  # noqa: E402

from backend.mcp.core.registry import SafetyClass, ToolGroup, ToolSpec  # noqa: E402
from backend.mcp.core.transport import _register_delegate  # noqa: E402


class _DemoIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=64, description="account that owns the trade")
    trade_id: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=200)


class _DemoOut(BaseModel):
    ok: bool


def _demo_spec() -> ToolSpec:
    async def _handler(args, ctx):  # pragma: no cover - never invoked in these tests
        return _DemoOut(ok=True)

    return ToolSpec(
        name="trades_get",
        group=ToolGroup.TRADES,
        handler=_handler,
        input_schema=_DemoIn,
        output_schema=_DemoOut,
        safety_class=SafetyClass.READ_ONLY,
        mutating=False,
        exchange_facing=False,
        description="demo tool",
    )


class _FakeFast:
    """Captures the (fn, name, kwargs) a _register_delegate call passes to add_tool,
    then builds the real FastMCP tool so we can read its advertised parameters."""

    def __init__(self):
        from mcp.server.fastmcp import FastMCP

        self._real = FastMCP("probe", stateless_http=True, json_response=True)
        self.last_fn = None

    def add_tool(self, fn, *, name=None, description=None, **kwargs):
        self.last_fn = fn
        self._real.add_tool(fn, name=name, description=description, **kwargs)

    def advertised_schema(self, name: str) -> dict:
        for t in self._real._tool_manager.list_tools():
            if t.name == name:
                return t.parameters
        raise AssertionError(f"tool {name!r} not registered")


def test_delegate_advertises_real_input_schema_not_kwargs():
    """The advertised schema must expose the tool's real fields, never a single
    catch-all `kwargs` property."""
    fake = _FakeFast()
    _register_delegate(fake, server=object(), spec=_demo_spec())
    schema = fake.advertised_schema("trades_get")

    props = set(schema.get("properties", {}))
    assert props == {"account_id", "trade_id", "limit"}, props
    assert "kwargs" not in props
    # required reflects the model (optionals/defaults excluded)
    assert set(schema.get("required", [])) == {"account_id", "trade_id"}
    # field-level constraints survive to the wire
    acc = schema["properties"]["account_id"]
    assert acc.get("maxLength") == 64 and acc.get("minLength") == 1


@pytest.mark.asyncio
async def test_delegate_forwards_flat_kwargs_to_call_tool():
    """Whatever signature we advertise, the delegate must still hand call_tool a
    FLAT dict of the real fields (dispatch re-validates via input_schema(**raw))."""
    captured: dict = {}

    class _SpyServer:
        def principal_hint(self):
            return "http-agent"

        async def call_tool(self, name, arguments, *, principal, session_id):
            captured["name"] = name
            captured["arguments"] = arguments
            return {"isError": False, "structuredContent": {"ok": True}, "content": []}

    fake = _FakeFast()
    _register_delegate(fake, server=_SpyServer(), spec=_demo_spec())
    result = await fake.last_fn(account_id="acct-1", trade_id="t-9", limit=10)

    assert captured["name"] == "trades_get"
    assert captured["arguments"] == {"account_id": "acct-1", "trade_id": "t-9", "limit": 10}
    assert result["isError"] is False



@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_asgi_set_after_enable(mcp_pool):
    """After enable, app.state.mcp_asgi points at a real (non-None) ASGI app."""
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
    # set a token + enable scans group
    _, token_hash = (lambda gt: gt())(generate_token)  # ensure import used
    await mgr.config_repo.set_token_hash("a" * 64)
    cfg = await mgr.config_repo.get()
    await mgr.config_repo.update({"enabled_groups": ["scans"]}, expected_row_version=cfg.row_version)
    try:
        await mgr.enable()
        assert app.state.mcp_asgi is not None  # transport wired
        assert app.state.mcp_server is not None
    finally:
        await mgr.shutdown()
        assert app.state.mcp_asgi is None  # torn down on disable
