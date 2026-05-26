#!/usr/bin/env python3
"""Run DB migrations before app startup. Safe to run multiple times (idempotent).

Usage: python -m backend.migrate
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from backend.async_persistence import AsyncAnalysisDB

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    db = AsyncAnalysisDB(dsn=dsn)
    await db.connect()
    print("Migrations applied successfully.")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
