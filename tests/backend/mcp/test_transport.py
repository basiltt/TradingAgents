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
