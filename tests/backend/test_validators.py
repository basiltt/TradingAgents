"""Tests for backend URL validator — TASK-003."""

import pytest


def test_valid_http_url():
    from backend.validators import validate_backend_url

    result = validate_backend_url("http://localhost:4141", server_port=8000)
    assert result == "http://localhost:4141"


def test_valid_https_url():
    from backend.validators import validate_backend_url

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


def test_allow_localhost_different_port():
    from backend.validators import validate_backend_url

    result = validate_backend_url("http://127.0.0.1:4141", server_port=8000)
    assert result == "http://127.0.0.1:4141"


def test_reject_self_request():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="self"):
        validate_backend_url("http://127.0.0.1:8000", server_port=8000)


def test_reject_self_request_localhost():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="self"):
        validate_backend_url("http://localhost:8000", server_port=8000)


def test_allow_ipv6_loopback_different_port():
    from backend.validators import validate_backend_url

    result = validate_backend_url("http://[::1]:9000", server_port=8000)
    assert result == "http://[::1]:9000"


def test_reject_ipv6_loopback_self_request():
    from backend.validators import validate_backend_url

    with pytest.raises(ValueError, match="self"):
        validate_backend_url("http://[::1]:8000", server_port=8000)
