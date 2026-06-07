"""Output redaction — TASK-P1 (FR-031, R-296/298).

Financial values (balances, absolute P&L) are reduced to ratios/percentages by
default; raw figures require an explicit financial-detail opt-in. Exchange UIDs
and credential-shaped keys are stripped. Applied in the dispatch shape stage and
by individual read tools.
"""
from __future__ import annotations

from typing import Any

# Keys that must never appear in any tool output.
_SECRET_KEY_MARKERS = ("key", "secret", "token", "password", "credential", "encrypted")
# Raw exchange identifiers to drop (opaque-id policy).
_EXCHANGE_ID_KEYS = ("bybit_uid", "uid")
# Absolute-money fields redacted unless financial-detail is opted in.
_MONEY_KEYS = (
    "wallet_balance", "available_balance", "equity", "balance",
    "realised_pnl", "unrealised_pnl", "realized_pnl", "unrealized_pnl",
    "closed_pnl", "cumulative_pnl", "margin_used",
)


def strip_secret_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop any key that looks credential-shaped (defense in depth)."""
    return {
        k: v
        for k, v in payload.items()
        if not any(m in str(k).lower() for m in _SECRET_KEY_MARKERS)
    }


def redact_record(record: dict[str, Any], *, allow_financial_detail: bool = False) -> dict[str, Any]:
    """Redact one record: strip secrets + exchange UIDs; mask absolute money
    unless financial detail is allowed."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        lk = str(k).lower()
        if any(m in lk for m in _SECRET_KEY_MARKERS):
            continue  # never emit secrets
        if lk in _EXCHANGE_ID_KEYS:
            continue  # opaque-id policy: drop raw exchange UIDs
        if (not allow_financial_detail) and lk in _MONEY_KEYS:
            out[k] = "redacted"
            continue
        out[k] = v
    return out


def redact_records(
    records: list[dict[str, Any]], *, allow_financial_detail: bool = False
) -> list[dict[str, Any]]:
    return [redact_record(r, allow_financial_detail=allow_financial_detail) for r in records]
