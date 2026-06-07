"""Redaction tests — TASK-P1 (FR-031, AC-017)."""
from __future__ import annotations

from backend.mcp.core.redact import redact_record, redact_records, strip_secret_keys


def test_strip_secret_keys():
    r = strip_secret_keys({"id": "a", "api_key_encrypted": b"x", "api_secret": "s", "label": "L"})
    assert r == {"id": "a", "label": "L"}


def test_redact_drops_exchange_uid():
    r = redact_record({"id": "acc1", "bybit_uid": "999", "label": "L"})
    assert "bybit_uid" not in r
    assert r["id"] == "acc1"


def test_redact_masks_money_by_default():
    r = redact_record({"id": "a", "equity": 1234.5, "available_balance": 100.0})
    assert r["equity"] == "redacted"
    assert r["available_balance"] == "redacted"


def test_redact_allows_money_with_optin():
    r = redact_record({"id": "a", "equity": 1234.5}, allow_financial_detail=True)
    assert r["equity"] == 1234.5


def test_redact_never_emits_secret_even_with_optin():
    r = redact_record({"api_key": "k", "equity": 1.0}, allow_financial_detail=True)
    assert "api_key" not in r


def test_redact_records_batch():
    out = redact_records([{"id": 1, "balance": 5.0}, {"id": 2, "balance": 6.0}])
    assert all(o["balance"] == "redacted" for o in out)
