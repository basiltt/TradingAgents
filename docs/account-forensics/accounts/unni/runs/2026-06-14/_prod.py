"""Read-only production DB helper for the Unni forensic investigation.

ALWAYS read-only against prod (157.173.124.192). Never writes.
Usage:
    from _prod import prod_query, prod_one, prod_val, ACCT, run
    rows = run(prod_query("select ... where account_id=$1", ACCT))
"""
from __future__ import annotations
import asyncio
import asyncpg
import sys
from typing import Any

# Force UTF-8 so Δ, arrows, etc. don't crash on the Windows cp1252 console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROD_DSN = "postgresql://postgres:Mywings123@157.173.124.192:5432/tradingagents"
LOCAL_DSN = "postgresql://postgres:Mywings123@localhost:5432/tradingagents"
ACCT = "3aca7442-2bd0-44c6-b4ef-bc46a9593f35"   # Unni - Demo (active)
ACCT_LABEL = "Unni - Demo"

_pool: dict[str, Any] = {}

async def _conn(dsn: str = PROD_DSN):
    return await asyncpg.connect(dsn)

async def prod_query(sql: str, *args, dsn: str = PROD_DSN):
    c = await _conn(dsn)
    try:
        rows = await c.fetch(sql, *args)
        return [dict(r) for r in rows]
    finally:
        await c.close()

async def prod_one(sql: str, *args, dsn: str = PROD_DSN):
    c = await _conn(dsn)
    try:
        r = await c.fetchrow(sql, *args)
        return dict(r) if r else None
    finally:
        await c.close()

async def prod_val(sql: str, *args, dsn: str = PROD_DSN):
    c = await _conn(dsn)
    try:
        return await c.fetchval(sql, *args)
    finally:
        await c.close()

def run(coro):
    return asyncio.run(coro)

def p(title: str):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
