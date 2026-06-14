import sys; sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, ACCT

# Brother account id for the second affected row
BROTHER = run(prod_one("select id from trading_accounts where label='Brother - Demo' and is_active=1"))
BRO = BROTHER["id"] if BROTHER else None

p("Does a closed_pnl_records table exist, and what columns?")
cols = run(prod_query("""
    select column_name, data_type from information_schema.columns
    where table_name='closed_pnl_records' order by ordinal_position
"""))
if cols:
    print("  columns:", [c["column_name"] for c in cols])
else:
    print("  NO closed_pnl_records table; searching for pnl-ish tables...")
    t = run(prod_query("select table_name from information_schema.tables where table_name ilike '%pnl%' or table_name ilike '%closed%'"))
    print("  candidates:", [x["table_name"] for x in t])

p("Stored closed_pnl_records rows for Unni ESPORTS (if table exists)")
for label, aid in [("Unni", ACCT), ("Brother", BRO)]:
    if not aid:
        continue
    try:
        rows = run(prod_query("""
            select * from closed_pnl_records
            where account_id=$1 and symbol='ESPORTSUSDT'
            order by 1 desc limit 5
        """, aid))
        print(f"  {label}: {len(rows)} stored ESPORTS closed_pnl_records rows")
        for r in rows:
            # print the money-relevant fields generically
            keys = [k for k in r.keys() if any(s in k.lower() for s in ('pnl','price','fee','side','symbol','time','exit','qty'))]
            print("   ", {k: r[k] for k in keys})
    except Exception as e:
        print(f"  {label}: query err -> {e}")

p("Any closed_pnl_records rows AT ALL for Unni (window sanity)")
try:
    n = run(prod_one("select count(*) c, min(1) from closed_pnl_records where account_id=$1", ACCT))
    print("  total Unni closed_pnl_records rows:", n)
except Exception as e:
    print("  err:", e)
