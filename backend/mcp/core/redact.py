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
# Absolute-money field MARKERS — substring-matched (so total_equity, net_pnl,
# usdt_balance, account_balance, position_value, realised_pnl, funding_fee,
# wallet_balance, notional, etc. are all caught, like secrets are). Deliberately
# does NOT include public market prices (entry/mark/liq price are not account
# money) — only absolute account-money figures that the contract reduces to
# ratios unless the financial-detail opt-in is set.
_MONEY_MARKERS = (
    "balance",
    "equity",
    "pnl",
    "margin",
    "notional",
    "wallet",
    "funding",
    "realised",
    "realized",
    "fee",
    "_value",
    "position_value",
    "cost",
)
# Ratio/percentage suffixes that are SAFE to emit (the redacted representation of
# money). A key matching these is never treated as absolute money.
_RATIO_MARKERS = ("_pct", "_ratio", "_rate", "percent", "_pnl_pct")


def _is_money_key(lk: str) -> bool:
    # Ratio/percentage fields are SAFE (they're the redacted-by-default
    # representation) even if they also contain a money marker like "pnl"
    # (e.g. unrealised_pnl_pct, pnl_ratio, roi_pct). Never mask those.
    if any(r in lk for r in _RATIO_MARKERS):
        return False
    return any(m in lk for m in _MONEY_MARKERS)


def strip_secret_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop any key that looks credential-shaped (defense in depth)."""
    return {
        k: v
        for k, v in payload.items()
        if not any(m in str(k).lower() for m in _SECRET_KEY_MARKERS)
    }


def redact_record(record: dict[str, Any], *, allow_financial_detail: bool = False) -> dict[str, Any]:
    """Redact one record RECURSIVELY: strip secrets + exchange UIDs at every
    depth; mask absolute money unless financial detail is allowed."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        lk = str(k).lower()
        if any(m in lk for m in _SECRET_KEY_MARKERS):
            continue  # never emit secrets (any depth)
        if lk in _EXCHANGE_ID_KEYS:
            continue  # opaque-id policy: drop raw exchange UIDs
        if (not allow_financial_detail) and _is_money_key(lk):
            out[k] = "redacted"
            continue
        # recurse into nested structures
        if isinstance(v, dict):
            out[k] = redact_record(v, allow_financial_detail=allow_financial_detail)
        elif isinstance(v, list):
            out[k] = [
                redact_record(item, allow_financial_detail=allow_financial_detail)
                if isinstance(item, dict) else item
                for item in v
            ]
        else:
            out[k] = v
    return out


def redact_records(
    records: list[dict[str, Any]], *, allow_financial_detail: bool = False
) -> list[dict[str, Any]]:
    return [redact_record(r, allow_financial_detail=allow_financial_detail) for r in records]
