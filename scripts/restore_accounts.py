"""
Re-insert the 24 backed-up trading_accounts into the freshly recreated prod DB.

- created_at / updated_at  -> today (now, UTC, app's ISO format)
- id, label, account_type, masked key, encrypted blobs, key_version,
  is_active, deleted_at, bybit_uid, include_in_analytics, strategy_cohort -> preserved
- last_connected_at -> NULL (fresh), last_error -> NULL (fresh)

Read-only against the backup file; writes only INSERTs to prod.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import psycopg2

PROD = dict(host="157.173.124.192", port=5432, dbname="tradingagents",
            user="postgres", password="Mywings123", connect_timeout=15)

NOW = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

backup_dir = sorted(Path(__file__).resolve().parent.parent.glob("backups/accounts_*"))[-1]
rows = json.loads((backup_dir / "trading_accounts_full.json").read_text(encoding="utf-8"))

print("Backup dir:", backup_dir.name)
print("Rows to insert:", len(rows))
print("Setting created_at/updated_at =", NOW)

conn = psycopg2.connect(**PROD)
conn.autocommit = False
cur = conn.cursor()

# Safety: ensure table is empty before we insert (fresh DB expected)
cur.execute("select count(*) from trading_accounts")
pre = cur.fetchone()[0]
if pre != 0:
    raise SystemExit(f"ABORT: trading_accounts already has {pre} rows; not inserting blindly.")

insert_sql = """
insert into trading_accounts
 (id, label, account_type, api_key_masked, api_key_encrypted, api_secret_encrypted,
  key_version, is_active, deleted_at, bybit_uid, last_connected_at, last_error,
  created_at, updated_at, include_in_analytics, strategy_cohort)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""

def blob(rec, col):
    v = rec.get(col)
    if isinstance(v, dict) and "__bytea_hex__" in v:
        return psycopg2.Binary(bytes.fromhex(v["__bytea_hex__"]))
    return None

inserted = 0
for r in rows:
    cur.execute(insert_sql, (
        r["id"], r["label"], r["account_type"], r["api_key_masked"],
        blob(r, "api_key_encrypted"), blob(r, "api_secret_encrypted"),
        r["key_version"], r["is_active"], r["deleted_at"], r["bybit_uid"],
        None, None,                      # last_connected_at, last_error -> fresh
        NOW, NOW,                        # created_at, updated_at -> today
        r["include_in_analytics"], r["strategy_cohort"],
    ))
    inserted += 1

cur.execute("select count(*), count(*) filter (where is_active=1), "
            "count(*) filter (where deleted_at is not null) from trading_accounts")
total, active, deleted = cur.fetchone()
print(f"Inserted={inserted}  total={total}  active={active}  soft_deleted={deleted}")

if total != len(rows):
    conn.rollback()
    raise SystemExit("ABORT: count mismatch, rolled back.")

conn.commit()
print("COMMIT OK")
cur.close()
conn.close()
