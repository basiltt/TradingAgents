"""MCP bearer-token authentication — TASK-P0-07.

Trading-free core. A `TokenAuthenticator` protocol with a bearer implementation
that constant-time-compares the SHA-256 of the presented token against the
stored hash. The token is never logged or returned.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol


@dataclass(frozen=True)
class Principal:
    """The authenticated caller identity (no secret material)."""

    token_id: str


def hash_token(plaintext: str) -> str:
    """SHA-256 hex of the token (what we persist; never the plaintext)."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Generate a CSPRNG bearer token. Returns (plaintext, sha256_hash)."""
    plaintext = secrets.token_urlsafe(32)  # >=256 bits
    return plaintext, hash_token(plaintext)


class TokenAuthenticator(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Optional[Principal]: ...


class BearerAuthenticator:
    """Validate `Authorization: Bearer <token>` against a stored SHA-256 hash."""

    def __init__(self, token_hash: Optional[str]) -> None:
        self._token_hash = token_hash

    def authenticate(self, headers: Mapping[str, str]) -> Optional[Principal]:
        # Fail closed when no token is configured.
        if not self._token_hash:
            return None
        raw = _header(headers, "authorization")
        if not raw:
            return None
        parts = raw.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        presented_hash = hash_token(parts[1].strip())
        if not hmac.compare_digest(presented_hash, self._token_hash):
            return None
        # token_id is a stable, non-secret identifier (first 12 hex of the hash).
        return Principal(token_id=self._token_hash[:12])


def _header(headers: Mapping[str, str], key: str) -> Optional[str]:
    """Case-insensitive header lookup."""
    for k, v in headers.items():
        if k.lower() == key:
            return v
    return None
