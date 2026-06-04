"""Static sector mapping for crypto symbols.

Used by the auto-trade sector concentration limit to prevent
opening too many positions in correlated assets.
"""

from __future__ import annotations

# Sector assignments for popular USDT-margined perpetuals.
# Unknown symbols default to "other" which is exempt from the sector limit.
_SECTOR_MAP: dict[str, str] = {
    # Layer 1
    "BTCUSDT": "l1", "ETHUSDT": "l1", "SOLUSDT": "l1", "AVAXUSDT": "l1",
    "ADAUSDT": "l1", "DOTUSDT": "l1", "ATOMUSDT": "l1", "NEARUSDT": "l1",
    "APTUSDT": "l1", "SUIUSDT": "l1", "SEIUSDT": "l1", "TONUSDT": "l1",
    "INJUSDT": "l1", "TIAUSDT": "l1", "FTMUSDT": "l1", "ALGOUSDT": "l1",
    "XLMUSDT": "l1", "XRPUSDT": "l1", "TRXUSDT": "l1", "HBARUSDT": "l1",
    "ICPUSDT": "l1", "KASUSDT": "l1",
    # Layer 2 / Scaling
    "MATICUSDT": "l2", "ARBUSDT": "l2", "OPUSDT": "l2", "STRKUSDT": "l2",
    "MANTAUSDT": "l2", "METISUSDT": "l2", "ZKUSDT": "l2", "SCROLLUSDT": "l2",
    "IMXUSDT": "l2",
    # DeFi
    "UNIUSDT": "defi", "AAVEUSDT": "defi", "MKRUSDT": "defi", "CRVUSDT": "defi",
    "LDOUSDT": "defi", "DYDXUSDT": "defi", "SNXUSDT": "defi", "COMPUSDT": "defi",
    "SUSHIUSDT": "defi", "1INCHUSDT": "defi", "JUPUSDT": "defi", "PENDLEUSDT": "defi",
    "RAYUSDT": "defi",
    # Meme
    "DOGEUSDT": "meme", "SHIBUSDT": "meme", "SHIB1000USDT": "meme",
    "PEPEUSDT": "meme", "PEPE1000USDT": "meme", "FLOKIUSDT": "meme",
    "BONKUSDT": "meme", "WIFUSDT": "meme", "MEMEUSDT": "meme",
    "BRETTUSDT": "meme", "MOGTUSDT": "meme",
    # AI / Compute
    "FETUSDT": "ai", "RENDERUSDT": "ai", "TAOUSDT": "ai", "ARUSDT": "ai",
    "AKTUSDT": "ai", "OCEANUSDT": "ai", "WLDUSDT": "ai", "AIUSDT": "ai",
    "VIRTUSDT": "ai",
    # Gaming / Metaverse
    "AXSUSDT": "gaming", "SANDUSDT": "gaming", "MANAUSDT": "gaming",
    "ILVUSDT": "gaming", "GALAUSDT": "gaming", "ENJUSDT": "gaming",
    "RONUSDT": "gaming", "PIXELUSDT": "gaming", "BEAMUSDT": "gaming",
    "XAIUSDT": "gaming", "BIGTIMEUSDT": "gaming",
    # Infrastructure / Oracle
    "LINKUSDT": "infra", "GRTUSDT": "infra", "FILUSDT": "infra",
    "THETAUSDT": "infra", "PYTHUSDT": "infra",
    # Exchange tokens
    "BNBUSDT": "exchange", "OKBUSDT": "exchange", "CAKEUSDT": "exchange",
}


def get_sector(symbol: str) -> str:
    """Return the sector for a symbol, or 'other' if unmapped."""
    return _SECTOR_MAP.get(symbol, "other")
