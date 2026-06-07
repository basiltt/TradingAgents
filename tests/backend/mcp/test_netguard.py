"""Tests for Host/Origin allowlist — TASK-P0-09 (DNS-rebind defense, AC-013)."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "127.0.0.1", "localhost"],
)
def test_loopback_host_allowed(host):
    from backend.mcp.core.netguard import host_origin_allowed

    assert host_origin_allowed(host=host, origin=None)


@pytest.mark.parametrize(
    "host",
    ["attacker.com", "evil.com:8000", "10.0.0.5:8000", "192.168.1.1"],
)
def test_non_loopback_host_rejected(host):
    from backend.mcp.core.netguard import host_origin_allowed

    assert not host_origin_allowed(host=host, origin=None)


def test_absent_origin_allowed_for_local_bridge():
    from backend.mcp.core.netguard import host_origin_allowed

    # mcp-remote / Claude Code send Host loopback and NO Origin
    assert host_origin_allowed(host="127.0.0.1:8000", origin=None)


def test_present_non_loopback_origin_rejected():
    from backend.mcp.core.netguard import host_origin_allowed

    assert not host_origin_allowed(host="127.0.0.1:8000", origin="https://attacker.com")


def test_present_loopback_origin_allowed():
    from backend.mcp.core.netguard import host_origin_allowed

    assert host_origin_allowed(host="127.0.0.1:8000", origin="http://localhost:8000")
