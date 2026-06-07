"""Symbols read tools — TASK-P1-09 (symbol search + sector lookup)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.registry import SafetyClass, ToolGroup, tool


class SymbolsSearchIn(BaseModel):
    query: str = Field(default="", max_length=32)
    limit: int = Field(default=50, ge=1, le=200)


class SymbolsSearchOut(BaseModel):
    symbols: list[str]
    count: int
    truncated: bool


@tool(
    name="symbols_search",
    group=ToolGroup.SYMBOLS,
    input_schema=SymbolsSearchIn,
    output_schema=SymbolsSearchOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def symbols_search(args: SymbolsSearchIn, ctx: Any) -> SymbolsSearchOut:
    """Search the tradable crypto symbol universe by case-insensitive substring; bounded result list."""
    import asyncio

    from tradingagents.dataflows.bybit_data import get_valid_symbols

    all_symbols = await asyncio.to_thread(get_valid_symbols)
    q = args.query.upper().strip()
    matches = sorted(s for s in all_symbols if not q or q in s.upper())
    truncated = len(matches) > args.limit
    return SymbolsSearchOut(symbols=matches[: args.limit], count=min(len(matches), args.limit), truncated=truncated)


class SymbolGetIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)


class SymbolGetOut(BaseModel):
    symbol: str
    tradable: bool
    sector: Optional[str] = None


@tool(
    name="symbols_get",
    group=ToolGroup.SYMBOLS,
    input_schema=SymbolGetIn,
    output_schema=SymbolGetOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def symbols_get(args: SymbolGetIn, ctx: Any) -> SymbolGetOut:
    """Get one symbol's tradability + sector classification (if the sector service is available)."""
    import asyncio

    from tradingagents.dataflows.bybit_data import get_valid_symbols

    sym = args.symbol.upper().strip()
    all_symbols = await asyncio.to_thread(get_valid_symbols)
    tradable = sym in {s.upper() for s in all_symbols}

    sector: Optional[str] = None
    svc = ctx.services.sector_service
    if svc is not None:
        try:
            # get_sector is synchronous (in-memory classification cache)
            sector = svc.get_sector(sym)
        except Exception:  # noqa: BLE001 — sector lookup is best-effort enrichment
            sector = None
    return SymbolGetOut(symbol=sym, tradable=tradable, sector=sector)
