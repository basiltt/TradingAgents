"""Symbols / ticker-list endpoint — wraps Bybit symbol cache."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["symbols"])


@router.get("/symbols")
async def list_symbols(
    asset_type: str = Query("crypto", pattern="^(stock|crypto)$"),
):
    if asset_type != "crypto":
        return {"symbols": []}

    import asyncio

    from tradingagents.dataflows.bybit_data import get_valid_symbols

    symbols = await asyncio.to_thread(get_valid_symbols)
    return {"symbols": sorted(symbols)}
