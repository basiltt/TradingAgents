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


def test_redact_masks_exchange_money_fields_not_just_balance():
    """Position/trade rows carry absolute-money fields whose keys don't contain
    balance/equity/pnl/margin — these must still be masked by default."""
    row = {
        "symbol": "BTCUSDT",
        "position_value": 30000.0,
        "notional": 30000.0,
        "cum_realised_pnl": 120.0,  # has pnl
        "realised_value": 99.0,
        "funding_fee": 1.2,
        "exec_fee": 0.5,
        "trade_cost": 12.0,
        "unrealised_pnl_pct": 3.2,  # a RATIO — must survive
        "entry_price": 60000.0,     # public market price — must survive
    }
    r = redact_record(row)
    for masked in ("position_value", "notional", "realised_value", "funding_fee", "exec_fee", "trade_cost"):
        assert r[masked] == "redacted", f"{masked} leaked raw"
    # ratios + public prices are NOT account money → preserved
    assert r["unrealised_pnl_pct"] == 3.2  # _pct ratio survives despite 'pnl' substring
    assert r["entry_price"] == 60000.0


def test_redact_money_fields_appear_with_optin():
    row = {"position_value": 30000.0, "funding_fee": 1.2}
    r = redact_record(row, allow_financial_detail=True)
    assert r["position_value"] == 30000.0 and r["funding_fee"] == 1.2
