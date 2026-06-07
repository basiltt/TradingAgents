"""Host/Origin allowlist — TASK-P0-09.

DNS-rebinding defense for the loopback-only MVP transport: the `Host` header
must be a loopback authority, and any *present* browser `Origin` must also be
loopback. A bridge client (mcp-remote / Claude Code) sends no Origin, which is
allowed.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _hostname(authority: str) -> str:
    """Extract the bare hostname from a Host/authority string (drop the port)."""
    authority = authority.strip()
    if authority.startswith("["):  # bracketed IPv6, e.g. [::1]:8000
        end = authority.find("]")
        if end != -1:
            return authority[1:end]
    # split off :port (IPv4 / hostname)
    if ":" in authority and authority.count(":") == 1:
        return authority.rsplit(":", 1)[0]
    return authority


def _is_loopback_host(authority: Optional[str]) -> bool:
    if not authority:
        return False
    return _hostname(authority) in _LOOPBACK_HOSTS


# Public alias — the single source of truth for "is this a loopback authority?".
# Reused by preflight, the control-plane router's endpoint builder, and anywhere
# else that must agree with what host_origin_allowed() actually enforces. Do NOT
# re-implement this check elsewhere; membership/normalization must stay in lockstep
# with _LOOPBACK_HOSTS so a UI "loopback" badge never disagrees with the guard.
def is_loopback_host(authority: Optional[str]) -> bool:
    return _is_loopback_host(authority)


def _is_loopback_origin(origin: str) -> bool:
    parts = urlsplit(origin)
    return parts.hostname in _LOOPBACK_HOSTS


def host_origin_allowed(*, host: Optional[str], origin: Optional[str]) -> bool:
    """True if the request passes the loopback Host + Origin allowlist."""
    if not _is_loopback_host(host):
        return False
    if origin is None or origin == "":
        return True  # local bridge clients send no Origin
    return _is_loopback_origin(origin)
