"""Backend URL validator with SSRF protection — TASK-003."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

_CGN_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")


def _allow_local() -> bool:
    """Check if local/private addresses are permitted (for co-located proxies)."""
    return os.environ.get("ALLOW_LOCAL_LLM_BACKEND", "").lower() in ("1", "true", "yes")


def validate_backend_url(url: str, server_port: int) -> str:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Invalid URL scheme '{parsed.scheme}': only http and https are allowed"
        )

    if not parsed.hostname:
        raise ValueError("URL must include a hostname")

    hostname = parsed.hostname
    port = parsed.port

    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from None

    if not infos:
        raise ValueError(f"No addresses found for hostname: {hostname}")

    resolved_ip = infos[0][4][0]

    try:
        addr = ipaddress.ip_address(resolved_ip)
    except ValueError:
        raise ValueError(f"Invalid resolved IP: {resolved_ip}") from None

    # Skip private/loopback checks when local backends are explicitly allowed
    if not _allow_local():
        if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved:
            raise ValueError(
                f"private/internal address blocked: {hostname} resolves to {resolved_ip}"
            )

        if isinstance(addr, ipaddress.IPv4Address) and addr in _CGN_NETWORK:
            raise ValueError(
                f"private/internal address blocked: {hostname} resolves to CGN range {resolved_ip}"
            )

        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:  # pragma: no cover
            v4 = addr.ipv4_mapped
            if v4.is_private or v4.is_link_local or v4.is_reserved or v4.is_loopback:
                raise ValueError(
                    f"private/internal address blocked: IPv4-mapped {resolved_ip}"
                )

    return url
