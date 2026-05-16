"""Tests for backend.crypto — Fernet encryption utilities."""


import pytest


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", key)


def test_encrypt_decrypt_roundtrip():
    from backend.crypto import decrypt_value, encrypt_value

    plaintext = "my-secret-api-key-12345"
    encrypted = encrypt_value(plaintext)
    assert isinstance(encrypted, bytes)
    assert decrypt_value(encrypted) == plaintext


def test_encrypt_produces_different_ciphertexts():
    from backend.crypto import encrypt_value

    a = encrypt_value("same")
    b = encrypt_value("same")
    assert a != b


def test_decrypt_wrong_key_raises(monkeypatch):
    from cryptography.fernet import Fernet

    from backend.crypto import decrypt_value, encrypt_value

    encrypted = encrypt_value("secret")
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(RuntimeError, match="Failed to decrypt"):
        decrypt_value(encrypted)


def test_decrypt_memoryview_input():
    """decrypt_value accepts memoryview (PostgreSQL bytea column scenario)."""
    from backend.crypto import decrypt_value, encrypt_value

    plaintext = "memoryview-secret-key"
    encrypted = encrypt_value(plaintext)
    result = decrypt_value(memoryview(encrypted))
    assert result == plaintext


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ACCOUNTS_ENCRYPTION_KEY")
    from backend.crypto import encrypt_value

    with pytest.raises(RuntimeError, match="ACCOUNTS_ENCRYPTION_KEY"):
        encrypt_value("x")


def test_mask_api_key():
    from backend.crypto import mask_api_key

    assert mask_api_key("abcdefghijklmn") == "abcd****klmn"
    assert mask_api_key("short") == "****"
    assert mask_api_key("12345678") == "****"
    assert mask_api_key("123456789") == "1234****6789"


def test_validate_encryption_key():
    from backend.crypto import validate_encryption_key

    validate_encryption_key()


def test_validate_encryption_key_bad_key(monkeypatch):
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    from backend.crypto import validate_encryption_key

    with pytest.raises(Exception):
        validate_encryption_key()
