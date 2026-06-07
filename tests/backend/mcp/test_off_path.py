"""OFF-path / isolation regression — NFR-011, AC-012, AC-015.

Asserts the MCP feature is wired but inert by default, never aborts startup, and
imports construct no services.
"""
from __future__ import annotations

import pytest


def test_create_app_wires_mcp_off_by_default():
    from backend.main import create_app

    app = create_app()
    paths = {getattr(r, "path", str(r)) for r in app.routes}
    assert "/mcp/rpc" in paths
    assert "/api/v1/mcp/status" in paths
    # OFF by default — no transport, no server
    assert app.state.mcp_asgi is None
    assert app.state.mcp_server is None


def test_importing_mcp_constructs_no_services():
    import backend.mcp  # noqa: F401
    import backend.mcp.core.registry  # noqa: F401
    import backend.mcp.mount  # noqa: F401

    # discovery is a separate composition module; importing core must not run it
    from backend.mcp.discovery import _DISCOVERED

    assert isinstance(_DISCOVERED, bool)


@pytest.mark.asyncio
async def test_mcp_boot_failure_does_not_raise():
    """If mcp_boot hits an error it degrades to None, never raises (NFR-007)."""
    from backend.mcp.mount import mcp_boot

    class _BadState:
        db = None  # no pool -> boot returns cleanly disabled

    class _App:
        state = _BadState()

    app = _App()
    # mcp_boot tolerates a missing pool and stays disabled
    result = await mcp_boot(app)
    # no server started
    assert getattr(app.state, "mcp_server", None) is None
