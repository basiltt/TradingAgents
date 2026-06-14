"""Bybit V5 endpoint -> (channel, endpoint_class) registry (TASK-0.1, FR-001/005).

Single source of truth mapping each Bybit REST path to:
- the rate-gate CHANNEL it is charged to ("public" = per-IP market data,
  "private" = per-UID account/order/position/wallet), and
- a per-endpoint CLASS used by the per-account/endpoint sub-limiter.

Bybit classifies /v5/market/* as public (IP-limited only); everything that
requires a signature (orders, positions, wallet, leverage) is per-UID private.
Charging public market reads to the private channel — as the client did before
this change — wastes the scarce private budget (100/5s) and is the bug FR-001
fixes.
"""

from __future__ import annotations

PUBLIC = "public"
PRIVATE = "private"


class EndpointClassificationError(KeyError):
    """Raised when a Bybit path used by _request has no registry mapping.

    A hard error (not a silent default) so a new endpoint cannot be charged to
    the wrong channel/class by accident — the caller must register it here.
    """


# path -> (channel, endpoint_class). endpoint_class drives the per-account
# 1-second sub-limiter; market reads share a single "market" class but are
# only IP-bounded (no per-UID sub-limit).
_REGISTRY: dict[str, tuple[str, str]] = {
    # ── public / per-IP market data ────────────────────────────────────────
    "/v5/market/tickers": (PUBLIC, "market"),
    "/v5/market/instruments-info": (PUBLIC, "market"),
    "/v5/market/kline": (PUBLIC, "market"),
    "/v5/market/time": (PUBLIC, "market"),
    "/v5/market/orderbook": (PUBLIC, "market"),
    # ── private / per-UID ──────────────────────────────────────────────────
    "/v5/order/create": (PRIVATE, "order_create"),
    "/v5/order/cancel": (PRIVATE, "order_cancel"),
    "/v5/order/amend": (PRIVATE, "order_amend"),
    "/v5/order/history": (PRIVATE, "order_query"),
    "/v5/order/realtime": (PRIVATE, "order_query"),
    "/v5/position/list": (PRIVATE, "position_list"),
    "/v5/position/set-leverage": (PRIVATE, "set_leverage"),
    "/v5/position/trading-stop": (PRIVATE, "set_trading_stop"),
    "/v5/position/closed-pnl": (PRIVATE, "position_list"),
    "/v5/account/wallet-balance": (PRIVATE, "wallet"),
    "/v5/account/info": (PRIVATE, "wallet"),
    "/v5/order/create-batch": (PRIVATE, "order_create"),
    "/v5/order/cancel-batch": (PRIVATE, "order_cancel"),
}

# Per-account, per-endpoint-class 1-second cap (≈80% of Bybit's non-VIP floor).
# Used by the rate gate's per-account sub-limiter. market = None => IP-bounded
# only (no per-UID sub-limit).
ENDPOINT_PER_SECOND_CAP: dict[str, int | None] = {
    "market": None,
    "order_create": 8,
    "order_cancel": 8,
    "order_amend": 8,
    "set_leverage": 8,
    "set_trading_stop": 8,
    "position_list": 40,
    "wallet": 40,
    "order_query": 20,
}


def classify_endpoint(path: str) -> tuple[str, str]:
    """Return (channel, endpoint_class) for a Bybit REST path.

    The path may include a query string; only the path portion is matched.
    Raises EndpointClassificationError for an unmapped path (FR-005).
    """
    clean = path.split("?", 1)[0]
    try:
        return _REGISTRY[clean]
    except KeyError as exc:
        raise EndpointClassificationError(
            f"Bybit path not in endpoint registry: {clean!r}. "
            "Add it to backend/services/bybit_endpoints.py with its "
            "(channel, endpoint_class)."
        ) from exc


def validate_registry() -> None:
    """Assert every private endpoint_class in the registry has a per-second cap
    entry (FR-005). A mapped path whose class is missing from
    ENDPOINT_PER_SECOND_CAP would be silently un-sub-limited (per-UID ban risk),
    so fail loudly at startup instead. Public/"market" is intentionally uncapped.
    """
    missing: list[str] = []
    for channel, ep_class in _REGISTRY.values():
        if channel == PRIVATE and ep_class not in ENDPOINT_PER_SECOND_CAP:
            missing.append(ep_class)
    if missing:
        raise EndpointClassificationError(
            f"Private endpoint classes missing a per-second cap: {sorted(set(missing))}. "
            "Add them to ENDPOINT_PER_SECOND_CAP."
        )

