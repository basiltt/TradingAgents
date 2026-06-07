"""Unit tests for the MCP control-plane endpoint helpers — connection-panel display.

These pin the *security-critical, FAIL-SAFE* display contract of the Connection panel.
The app has NO per-request auth — a loopback bind is the only thing between an attacker
and real-money trade placement — so the panel must never assert "safe" it cannot prove:

  * the advertised client URL is loopback (the transport guard rejects every non-loopback
    Host), echoing a *specific* loopback bind (::1) when that is what the server bound;
  * the port is the REAL listening socket port (ASGI scope), not an env guess;
  * the bind host is detected from the server's OWN argv (process truth across every
    first-party launcher), then env, and FAILS CLOSED to None/unknown — never defaulting
    to a reassuring 127.0.0.1;
  * `loopback_only` is true ONLY on positive proof of a loopback bind (0.0.0.0 / LAN /
    unknown all → not-true), so the UI cannot show "safe" while bound to all interfaces;
  * malformed env / out-of-range ports can never produce a malformed URL.

Pure helpers → no DB, no app lifespan required.
"""
from __future__ import annotations

import pytest

from backend.mcp.router import (
    _bind_host_from_argv,
    _coerce_port,
    _mcp_rpc_endpoint,
    _resolve_bind_host,
    _served_port,
)
from backend.mcp.core.netguard import is_loopback_host


class _Req:
    """Minimal stand-in exposing only what the helpers read: request.scope."""

    def __init__(self, server):
        self.scope = {"server": server}


# --- endpoint URL: loopback host, real port -------------------------------------------

def test_endpoint_is_loopback_with_real_port():
    url = _mcp_rpc_endpoint(_Req(("127.0.0.1", 8877)), "127.0.0.1")
    assert url == "http://127.0.0.1:8877/mcp/rpc"


def test_endpoint_defaults_loopback_when_bind_is_wildcard():
    # a 0.0.0.0 bind is not connectable; the client URL must fall back to 127.0.0.1
    url = _mcp_rpc_endpoint(_Req(("0.0.0.0", 8877)), "0.0.0.0")
    assert url == "http://127.0.0.1:8877/mcp/rpc"


def test_endpoint_echoes_ipv6_loopback_bracketed():
    # on an ::1-only loopback box, 127.0.0.1 may be unreachable — echo the real bind
    url = _mcp_rpc_endpoint(_Req(("::1", 8877)), "::1")
    assert url == "http://[::1]:8877/mcp/rpc"


def test_endpoint_path_matches_real_mount():
    from backend.mcp.mount import MCP_RPC_PATH

    url = _mcp_rpc_endpoint(_Req(("127.0.0.1", 8877)), "127.0.0.1")
    assert url.endswith(MCP_RPC_PATH)


def test_endpoint_never_malformed_on_bad_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_PORT", "  not-a-port  ")
    url = _mcp_rpc_endpoint(_Req(None), None)
    assert url == "http://127.0.0.1:8877/mcp/rpc"
    assert " " not in url


# --- port: real socket wins, then env, then default, range-checked --------------------

def test_port_prefers_asgi_scope_over_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_PORT", "9000")
    assert _served_port(_Req(("127.0.0.1", 8877))) == "8877"


def test_port_falls_back_to_env_when_scope_missing(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_PORT", "9000")
    assert _served_port(_Req(None)) == "9000"


def test_port_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_PORT", raising=False)
    assert _served_port(_Req(None)) == "8877"


@pytest.mark.parametrize("raw", [" 9000\n", "9000 ", "\t9000"])
def test_port_env_is_stripped(monkeypatch, raw):
    monkeypatch.setenv("TRADINGAGENTS_PORT", raw)
    assert _served_port(_Req(None)) == "9000"


@pytest.mark.parametrize("raw", ["abc", "", "80x", "12.5", "0", "-1", "70000", "99999"])
def test_port_invalid_or_out_of_range_falls_back(monkeypatch, raw):
    monkeypatch.setenv("TRADINGAGENTS_PORT", raw)
    assert _served_port(_Req(None)) == "8877"


def test_port_scope_out_of_range_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_PORT", "9000")
    assert _served_port(_Req(("127.0.0.1", 0))) == "9000"


@pytest.mark.parametrize("port", ["1", "443", "65535"])
def test_coerce_port_accepts_valid_range(port):
    assert _coerce_port(port) == port


@pytest.mark.parametrize("bad", ["0", "65536", "-5", "x", "", "  "])
def test_coerce_port_rejects_invalid(bad):
    assert _coerce_port(bad) is None


# --- bind host detection from argv (process truth) ------------------------------------

@pytest.mark.parametrize(
    "argv,expected",
    [
        (["uvicorn", "app", "--host", "127.0.0.1", "--port", "8877"], "127.0.0.1"),
        (["uvicorn", "app", "--host", "0.0.0.0"], "0.0.0.0"),       # docker / start-web.sh
        (["uvicorn", "app", "--host=0.0.0.0"], "0.0.0.0"),          # equals form
        (["gunicorn", "-b", "0.0.0.0:8877", "app"], "0.0.0.0"),     # gunicorn short
        (["gunicorn", "--bind", "[::1]:8877", "app"], "::1"),       # gunicorn ipv6
        (["gunicorn", "--bind=127.0.0.1:8877", "app"], "127.0.0.1"),
        (["uvicorn", "app", "--factory"], None),                    # no host → unknown
        (["pytest", "-q"], None),
    ],
)
def test_bind_host_from_argv(argv, expected):
    assert _bind_host_from_argv(argv) == expected


# --- _resolve_bind_host: argv first, env fallback, FAIL CLOSED ------------------------

def test_resolve_prefers_argv_over_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr("sys.argv", ["uvicorn", "app", "--host", "0.0.0.0"])
    # argv is the process truth — it must win even if a stale/wrong env var says loopback
    assert _resolve_bind_host() == ("0.0.0.0", "argv")


def test_resolve_falls_back_to_env_when_argv_silent(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_BIND_HOST", "0.0.0.0")
    monkeypatch.setattr("sys.argv", ["python", "-c", "import uvicorn; uvicorn.run(...)"])
    assert _resolve_bind_host() == ("0.0.0.0", "env")


def test_resolve_fails_closed_to_unknown(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_BIND_HOST", raising=False)
    monkeypatch.setattr("sys.argv", ["python", "-c", "..."])
    # NOT ("127.0.0.1", ...) — must never invent a reassuring loopback default
    assert _resolve_bind_host() == (None, "unknown")


# --- loopback_only is fail-safe: true ONLY on proof -----------------------------------

@pytest.mark.parametrize(
    "host,proven_loopback",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),       # the Docker exposure case — must NOT read as safe
        ("192.168.1.10", False),
        (None, False),            # unknown — must NOT read as safe
    ],
)
def test_loopback_only_positive_proof_only(host, proven_loopback):
    # mirrors get_config: bool(host) and is_loopback_host(host)
    assert (bool(host) and is_loopback_host(host)) is proven_loopback
