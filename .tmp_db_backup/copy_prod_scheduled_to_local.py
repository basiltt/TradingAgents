"""One-off: copy PRODUCTION scheduled-scan data into the LOCAL db for backtesting.

PROD is treated as STRICTLY READ-ONLY (only SELECTs run against it).
Insert order is FK-safe: scheduled_scans -> scans -> scan_results -> schedule_executions.
All inserts use ON CONFLICT (pk) DO NOTHING so the script is idempotent / re-runnable.
Everything is wrapped in a single LOCAL transaction with in-txn verification before commit.
"""
import os, asyncio
from pathlib import Path

# Load local .env
p = Path('.env')
for line in (p.read_text().splitlines() if p.exists() else []):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

LOCAL_DSN = os.environ['DATABASE_URL']
PROD_DSN = "postgresql://postgres:Mywings123@157-173-124-192.sslip.io:5432/tradingagents"

# Hard guards
assert 'localhost' in LOCAL_DSN or '127.0.0.1' in LOCAL_DSN, f"LOCAL must be localhost: {LOCAL_DSN}"
assert LOCAL_DSN.rsplit('/', 1)[-1].split('?')[0] == 'tradingagents', "LOCAL db name must be 'tradingagents'"
assert '157-173-124-192' in PROD_DSN, "PROD host guard"

import asyncpg

# (table, primary-key columns for ON CONFLICT, optional prod WHERE filter)
PLAN = [
    ("scheduled_scans",      ["id"],              None),
    ("scans",                ["scan_id"],         "schedule_id IS NOT NULL"),
    ("scan_results",         ["scan_id","ticker"],
        "scan_id IN (SELECT scan_id FROM scans WHERE schedule_id IS NOT NULL)"),
    ("schedule_executions",  ["id"],              None),
]

BATCH = 2000


async def common_columns(prod, loc, table):
    q = ("SELECT column_name FROM information_schema.columns "
         "WHERE table_name=$1 ORDER BY ordinal_position")
    pc = [r['column_name'] for r in await prod.fetch(q, table)]
    lc = set(r['column_name'] for r in await loc.fetch(q, table))
    # keep prod order, intersect with local
    return [c for c in pc if c in lc]


async def copy_table(prod, conn, table, pk_cols, where):
    cols = await common_columns(prod, conn, table)
    collist = ", ".join(f'"{c}"' for c in cols)
    where_sql = f" WHERE {where}" if where else ""
    rows = await prod.fetch(f"SELECT {collist} FROM {table}{where_sql}")
    if not rows:
        print(f"  {table}: 0 source rows")
        return 0
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    conflict = ", ".join(f'"{c}"' for c in pk_cols)
    insert = (f'INSERT INTO {table} ({collist}) VALUES ({placeholders}) '
              f'ON CONFLICT ({conflict}) DO NOTHING')
    inserted = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i+BATCH]
        await conn.executemany(insert, [tuple(r[c] for c in cols) for r in chunk])
        inserted += len(chunk)
        if len(rows) > BATCH:
            print(f"    {table}: {min(i+BATCH, len(rows))}/{len(rows)}")
    print(f"  {table}: {len(rows)} source rows processed ({len(cols)} cols)")
    return len(rows)


async def main():
    prod = await asyncio.wait_for(asyncpg.connect(dsn=PROD_DSN), timeout=30)
    loc = await asyncpg.connect(dsn=LOCAL_DSN)
    print("PROD:", PROD_DSN.split('@')[1])
    print("LOCAL:", LOCAL_DSN.split('@')[1])
    print()
    try:
        async with loc.transaction():
            for table, pk, where in PLAN:
                await copy_table(prod, loc, table, pk, where)
            print("\n  In-transaction local counts:")
            for t in ['scheduled_scans', 'scans', 'scan_results', 'schedule_executions']:
                print(f"    {t}: {await loc.fetchval(f'SELECT count(*) FROM {t}')}")
            print("\n  Committing...")
        print("  COMMITTED.")
    finally:
        await prod.close()
        await loc.close()


asyncio.run(main())
