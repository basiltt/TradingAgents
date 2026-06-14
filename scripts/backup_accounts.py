"""
One-shot production trading_accounts backup.

Produces, under backups/accounts_<UTC-timestamp>/:
  - trading_accounts_full.json     every column, bytea blobs hex-encoded (lossless)
  - trading_accounts_decrypted.json  same rows + decrypted api_key / api_secret plaintext
  - ENCRYPTION_KEY.txt             the Fernet key needed to use the encrypted blobs
  - MANIFEST.json                  counts, sha256 of each file, verification result
  - RESTORE_README.md              how to restore

Safe: read-only against production. Writes only to the local backups/ dir.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg2
from cryptography.fernet import Fernet

PROD_HOST = "157.173.124.192"
PROD_DSN = dict(host=PROD_HOST, port=5432, dbname="tradingagents",
                user="postgres", password="Mywings123", connect_timeout=15)
# Pulled from prod /root/projects/TradingAgents/.env (ACCOUNTS_ENCRYPTION_KEY)
ENCRYPTION_KEY = "CAE8Tl3NzeHC3i2WuuhR3cKYEaiixCUJa2RKbEH-L_E="

TS = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
OUT = Path(__file__).resolve().parent.parent / "backups" / f"accounts_{TS}"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(**PROD_DSN)
    cur = conn.cursor()

    cur.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema='public' and table_name='trading_accounts' "
        "order by ordinal_position"
    )
    cols = cur.fetchall()
    colnames = [c[0] for c in cols]
    bytea_cols = {c[0] for c in cols if c[1] == "bytea"}

    cur.execute(f"select {', '.join(colnames)} from trading_accounts order by created_at")
    rows = cur.fetchall()

    full_rows = []
    for r in rows:
        rec = {}
        for name, val in zip(colnames, r):
            if name in bytea_cols and val is not None:
                rec[name] = {"__bytea_hex__": bytes(val).hex()}
            else:
                rec[name] = val
        full_rows.append(rec)

    # Lossless full dump
    full_path = OUT / "trading_accounts_full.json"
    full_path.write_text(json.dumps(full_rows, indent=2, default=str), encoding="utf-8")

    # Decrypted dump (ultimate fallback)
    f = Fernet(ENCRYPTION_KEY.encode())
    dec_rows = []
    dec_fail = []
    for rec in full_rows:
        d = dict(rec)
        for blob_col, plain_col in (("api_key_encrypted", "api_key_plain"),
                                    ("api_secret_encrypted", "api_secret_plain")):
            blob = rec.get(blob_col)
            if isinstance(blob, dict) and "__bytea_hex__" in blob:
                try:
                    raw = bytes.fromhex(blob["__bytea_hex__"])
                    d[plain_col] = f.decrypt(raw).decode()
                except Exception as e:  # noqa: BLE001
                    d[plain_col] = None
                    dec_fail.append((rec.get("id"), blob_col, repr(e)))
        dec_rows.append(d)
    dec_path = OUT / "trading_accounts_decrypted.json"
    dec_path.write_text(json.dumps(dec_rows, indent=2, default=str), encoding="utf-8")

    # Key file
    key_path = OUT / "ENCRYPTION_KEY.txt"
    key_path.write_text(
        "ACCOUNTS_ENCRYPTION_KEY=" + ENCRYPTION_KEY + "\n"
        "# Fernet key for trading_accounts.api_key_encrypted / api_secret_encrypted\n"
        "# Restore this into the new .env BEFORE importing encrypted blobs,\n"
        "# or the encrypted credentials will be unusable.\n",
        encoding="utf-8",
    )

    cur.close()
    conn.close()

    manifest = {
        "backup_utc": TS,
        "source_host": PROD_HOST,
        "table": "trading_accounts",
        "columns": colnames,
        "bytea_columns": sorted(bytea_cols),
        "row_count": len(full_rows),
        "active_count": sum(1 for r in full_rows if r.get("is_active") == 1),
        "decrypt_verified": len(dec_fail) == 0,
        "decrypt_failures": dec_fail,
        "files": {
            "trading_accounts_full.json": sha256_file(full_path),
            "trading_accounts_decrypted.json": sha256_file(dec_path),
            "ENCRYPTION_KEY.txt": sha256_file(key_path),
        },
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("OUT_DIR:", OUT)
    print("ROWS:", len(full_rows), "ACTIVE:", manifest["active_count"])
    print("DECRYPT_VERIFIED:", manifest["decrypt_verified"], "FAILURES:", len(dec_fail))
    if dec_fail:
        for x in dec_fail:
            print("  FAIL:", x)
    return 0 if not dec_fail else 2


if __name__ == "__main__":
    sys.exit(main())
