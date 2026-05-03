"""Symbols / ticker-list endpoint — wraps Bybit symbol cache."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["symbols"])


@router.get("/symbols")
async def list_symbols(
    asset_type: str = Query("crypto", regex="^(stock|crypto)$"),
):
    if asset_type != "crypto":
        return {"symbols": []}

    from tradingagents.dataflows.bybit_data import get_valid_symbols

    symbols = get_valid_symbols()
    return {"symbols": sorted(symbols)}
