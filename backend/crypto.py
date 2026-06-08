"""Encryption utilities for trading account API credentials."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.environ.get("ACCOUNTS_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "ACCOUNTS_ENCRYPTION_KEY environment variable is required. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt_value(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_value(ciphertext: bytes | memoryview) -> str:
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    try:
        return _get_fernet().decrypt(ciphertext).decode()
    except InvalidToken:
        raise RuntimeError("Failed to decrypt value — encryption key may have been rotated") from None


def mask_api_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


def validate_encryption_key() -> None:
    f = _get_fernet()
    token = f.encrypt(b"healthcheck")
    result = f.decrypt(token)
    if result != b"healthcheck":
        raise RuntimeError("Encryption key validation failed")
