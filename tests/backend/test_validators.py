"""Tests for backend URL validator — TASK-003."""

import pytest


@pytest.fixture(autouse=True)
def _clear_allow_local(monkeypatch):
    """Ensure ALLOW_LOCAL_LLM_BACKEND is UNSET for every validator test.

    AI-CONTEXT: validators._allow_local() reads this env var; when it is truthy
    the SSRF private/loopback checks are intentionally skipped (for co-located
    proxies). If another test — or a developer's .env — leaks it as set, these
    rejection tests would silently pass-through and FAIL order-dependently
    (this was the root cause of the historical "14 validator failures under
    xdist/batched runs"). Clearing it here makes every test deterministic.
    """
    monkeypatch.delenv("ALLOW_LOCAL_LLM_BACKEND", raising=False)


def test_valid_http_url():
    from backend.validators import validate_backend_url
    from unittest.mock import patch
    import socket

    # Use a public IP so it passes validation
    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [
            (socket.AF_INET, None, None, None, ("93.184.216.34", None))
        ]
        result = validate_backend_url("http://example.com:4141", server_port=8000)
        assert result == "http://example.com:4141"


def test_valid_https_url():
    from backend.validators import validate_backend_url
    from unittest.mock import patch
    import socket

    # Mock DNS to a public IP (matches test_valid_http_url). Without this the test does a
    # REAL getaddrinfo lookup of api.openai.com, which makes it network-dependent and flaky
    # under sandboxed/offline runs (it intermittently failed "Cannot resolve hostname" only
    # in the full suite, never in isolation).
    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [
            (socket.AF_INET, None, None, None, ("93.184.216.34", None))
        ]
        result = validate_backend_url("https://api.openai.com/v1", server_port=8000)
        assert result == "https://api.openai.com/v1"


def test_reject_ftp_scheme():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="http.*https"):
        validate_backend_url("ftp://example.com", server_port=8000)


def test_reject_no_scheme():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError):
        validate_backend_url("example.com", server_port=8000)


def test_reject_private_ip_10():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://10.0.0.1:8080", server_port=8000)


def test_reject_private_ip_172():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://172.16.0.1:8080", server_port=8000)


def test_reject_private_ip_192():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://192.168.1.1:8080", server_port=8000)


def test_reject_link_local():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://169.254.1.1:8080", server_port=8000)


def test_reject_cgn():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://100.64.0.1:8080", server_port=8000)


def test_reject_localhost_different_port():
    """Loopback addresses are blocked regardless of port."""
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://127.0.0.1:4141", server_port=8000)


def test_reject_self_request():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://127.0.0.1:8000", server_port=8000)


def test_reject_self_request_localhost():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://localhost:8000", server_port=8000)


def test_reject_ipv6_loopback_different_port():
    """IPv6 loopback is blocked regardless of port."""
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://[::1]:9000", server_port=8000)


def test_reject_ipv6_loopback_self_request():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="private|internal"):
        validate_backend_url("http://[::1]:8000", server_port=8000)


def test_reject_no_hostname():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="hostname"):
        validate_backend_url("http://", server_port=8000)


def test_reject_unresolvable():
    from backend.validators import validate_backend_url
    from unittest.mock import patch
    import socket

    with patch("backend.validators.socket.getaddrinfo", side_effect=socket.gaierror):
        with pytest.raises(ValueError, match="Cannot resolve"):
            validate_backend_url("http://doesnotexist.invalid", server_port=8000)


def test_reject_no_addresses():
    from backend.validators import validate_backend_url
    from unittest.mock import patch

    with patch("backend.validators.socket.getaddrinfo", return_value=[]):
        with pytest.raises(ValueError, match="No addresses"):
            validate_backend_url("http://example.com", server_port=8000)


def test_loopback_default_port_80():
    from backend.validators import validate_backend_url
    from unittest.mock import patch

    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("127.0.0.1", None))]
        with pytest.raises(ValueError, match="private|internal"):
            validate_backend_url("http://localhost", server_port=80)


def test_loopback_default_port_443():
    from backend.validators import validate_backend_url
    from unittest.mock import patch

    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("127.0.0.1", None))]
        with pytest.raises(ValueError, match="private|internal"):
            validate_backend_url("https://localhost", server_port=443)


def test_ipv6_mapped_private():
    from backend.validators import validate_backend_url
    from unittest.mock import patch

    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("::ffff:192.168.1.1", None))]
        with pytest.raises(ValueError, match="private|internal"):
            validate_backend_url("http://example.com:9999", server_port=8000)


def test_invalid_resolved_ip():
    from backend.validators import validate_backend_url
    from unittest.mock import patch

    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("", None))]
        with pytest.raises(ValueError, match="Invalid resolved IP"):
            validate_backend_url("http://example.com:9999", server_port=8000)


def test_ipv6_mapped_private_blocked():
    """Covers validators.py:62-64: IPv6 mapped IPv4 private address."""
    from backend.validators import validate_backend_url
    from unittest.mock import patch
    import socket

    # ::ffff:192.168.1.1 is an IPv4-mapped IPv6 address in a private range
    with patch("backend.validators.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [
            (socket.AF_INET6, None, None, None, ("::ffff:192.168.1.1", None, 0, 0))
        ]
        with pytest.raises(ValueError, match="private"):
            validate_backend_url("http://example.com:9999", server_port=8000)


def test_reject_empty_string():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError):
        validate_backend_url("", server_port=8000)


def test_reject_whitespace_only():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError):
        validate_backend_url("   ", server_port=8000)


def test_reject_extremely_long_hostname():
    from backend.validators import validate_backend_url

    long_host = "a" * 300 + ".com"
    with pytest.raises(ValueError):
        validate_backend_url(f"http://{long_host}", server_port=8000)
