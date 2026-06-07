"""Tests for MCP bearer auth — TASK-P0-07."""
from __future__ import annotations

import pytest


def test_generate_token_returns_plaintext_and_hash():
    from backend.mcp.core.auth import generate_token, hash_token

    plaintext, token_hash = generate_token()
    assert isinstance(plaintext, str) and len(plaintext) >= 32
    assert token_hash == hash_token(plaintext)
    # two generations differ
    p2, _ = generate_token()
    assert p2 != plaintext


def test_bearer_authenticator_valid_token():
    from backend.mcp.core.auth import BearerAuthenticator, generate_token

    plaintext, token_hash = generate_token()
    auth = BearerAuthenticator(token_hash)
    principal = auth.authenticate({"authorization": f"Bearer {plaintext}"})
    assert principal is not None
    assert principal.token_id  # some stable id


@pytest.mark.parametrize(
    "headers",
    [
        {},  # missing
        {"authorization": "Bearer wrong"},  # invalid
        {"authorization": "Basic xyz"},  # wrong scheme
        {"authorization": "Bearer"},  # malformed
    ],
)
def test_bearer_authenticator_rejects(headers):
    from backend.mcp.core.auth import BearerAuthenticator, generate_token

    _, token_hash = generate_token()
    auth = BearerAuthenticator(token_hash)
    assert auth.authenticate(headers) is None


def test_authenticate_uses_constant_time_compare(monkeypatch):
    """Structural assertion: the code path goes through hmac.compare_digest."""
    import hmac

    from backend.mcp.core import auth as auth_mod
    from backend.mcp.core.auth import BearerAuthenticator, generate_token

    plaintext, token_hash = generate_token()
    calls = {"n": 0}
    real = hmac.compare_digest

    def _spy(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr(auth_mod.hmac, "compare_digest", _spy)
    BearerAuthenticator(token_hash).authenticate({"authorization": f"Bearer {plaintext}"})
    assert calls["n"] >= 1


def test_no_token_configured_denies_all():
    from backend.mcp.core.auth import BearerAuthenticator

    auth = BearerAuthenticator(None)
    assert auth.authenticate({"authorization": "Bearer anything"}) is None
