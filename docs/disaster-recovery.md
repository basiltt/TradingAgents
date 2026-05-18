# Disaster Recovery & Operations Runbook

## 1. Backup Strategy

### PostgreSQL Database

**Automated Daily Backups (pg_dump):**

```bash
#!/bin/bash
# /opt/tradingagents/scripts/backup.sh
set -euo pipefail

DB_URL="${DATABASE_URL}"
BACKUP_DIR="/backups/tradingagents"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Full logical backup with compression
pg_dump "$DB_URL" \
  --format=custom \
  --compress=9 \
  --file="$BACKUP_DIR/full_${TIMESTAMP}.dump"

# Prune old backups
find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: full_${TIMESTAMP}.dump ($(du -h "$BACKUP_DIR/full_${TIMESTAMP}.dump" | cut -f1))"
```

**Cron Schedule:**
```
# Daily at 02:00 UTC
0 2 * * * /opt/tradingagents/scripts/backup.sh >> /var/log/backup.log 2>&1
```

**WAL Archiving (Point-in-Time Recovery):**
```ini
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /backups/wal/%f'
```

**Restore Procedure:**
```bash
# Full restore
pg_restore --dbname=tradingagents_restore --clean --if-exists full_20250118_020000.dump

# Point-in-time recovery (to specific timestamp)
pg_restore --dbname=tradingagents_pitr full_20250118_020000.dump
pg_wal_replay --target-time="2025-01-18 15:30:00 UTC" /backups/wal/
```

### Application State

Analysis results, trade history, and account snapshots are stored in PostgreSQL.
No additional file-system backup is needed — the DB backup covers all persistent state.

---

## 2. Secret Rotation

### Encryption Key Rotation (ACCOUNTS_ENCRYPTION_KEY)

The accounts encryption key protects trading API credentials at rest. Rotation requires
re-encrypting all stored credentials.

**Rotation Procedure:**

1. Generate new key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. Run rotation script (encrypts under new key, keeps old key for rollback):
   ```bash
   python -m backend.scripts.rotate_encryption_key \
     --old-key "$ACCOUNTS_ENCRYPTION_KEY" \
     --new-key "$NEW_ACCOUNTS_ENCRYPTION_KEY"
   ```

3. Update environment/secrets store:
   ```bash
   # In your secrets manager (Vault, AWS Secrets Manager, etc.)
   vault kv put secret/tradingagents ACCOUNTS_ENCRYPTION_KEY="$NEW_KEY"
   ```

4. Rolling restart of application instances.

5. Verify: `GET /api/v1/accounts` returns valid data after rotation.

### API Key Rotation (LLM Providers)

LLM API keys (OPENAI_API_KEY, etc.) can be rotated without downtime:

1. Set new key in secrets manager.
2. Rolling restart — new requests use the new key immediately.
3. Revoke old key after confirming traffic flows on new key (check /metrics for errors).

### Database Credentials

1. Create new PostgreSQL role with same permissions.
2. Update DATABASE_URL in secrets manager.
3. Rolling restart.
4. Drop old role after connection drain (check `pg_stat_activity`).

---

## 3. Dead-Letter Queue (DLQ) for Failed Operations

### Architecture

Failed analysis runs and trade operations are captured in a `dead_letter` table
for manual inspection and retry.

### Schema

```sql
CREATE TABLE IF NOT EXISTS dead_letter (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation TEXT NOT NULL,        -- 'analysis', 'trade_open', 'trade_close', 'snapshot'
    payload JSONB NOT NULL,         -- Original request payload
    error_type TEXT NOT NULL,       -- Exception class name
    error_message TEXT NOT NULL,    -- Exception message (truncated to 2000 chars)
    stack_trace TEXT,               -- Full traceback
    attempt_count INTEGER DEFAULT 1,
    max_retries INTEGER DEFAULT 3,
    status TEXT DEFAULT 'pending',  -- 'pending', 'retrying', 'exhausted', 'resolved'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_retried_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT                -- operator who resolved it
);

CREATE INDEX idx_dead_letter_status ON dead_letter(status) WHERE status = 'pending';
CREATE INDEX idx_dead_letter_operation ON dead_letter(operation);
```

### Integration Points

- **Analysis failures** (timeout, graph error): captured in `_run_analysis` catch block
- **Trade execution failures** (exchange rejection, network timeout): captured in trade service
- **Snapshot failures** (WebSocket disconnect during snapshot): captured in scheduler

### Retry Policy

| Operation | Max Retries | Backoff | Alert After |
|-----------|------------|---------|-------------|
| analysis | 2 | 60s, 300s | 2 failures |
| trade_open | 3 | 5s, 15s, 60s | 1 failure |
| trade_close | 5 | 5s, 15s, 30s, 60s, 300s | 1 failure |
| snapshot | 3 | 30s, 60s, 300s | 3 failures |

### Monitoring

```promql
# Alert: DLQ items older than 1 hour
dead_letter_pending_count{age_bucket=">1h"} > 0

# Dashboard: DLQ rate by operation
rate(dead_letter_total[5m])
```

---

## 4. Incident Response

### Runbook: Database Connection Exhaustion

**Symptom:** `/api/v1/health` returns `{"status":"degraded","db":"unavailable"}`

1. Check active connections: `SELECT count(*) FROM pg_stat_activity WHERE datname='tradingagents';`
2. Kill idle-in-transaction connections older than 5min:
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle in transaction'
     AND state_change < NOW() - INTERVAL '5 minutes';
   ```
3. If pool exhausted, restart application (graceful: `kill -TERM <pid>`).

### Runbook: Analysis Stuck in "running"

**Symptom:** Analysis shows "running" for >30 minutes.

1. Check `/api/v1/health` — if `analyses_active` equals `analyses_max`, new analyses are blocked.
2. Cancel stuck analysis: `POST /api/v1/analysis/{run_id}/cancel`
3. If cancel fails, the orphan recovery runs on next restart.
4. Force recovery: restart the application — `recover_orphans()` marks stale runs as failed.

### Runbook: Trade Execution Failure

**Symptom:** Trade stuck in "pending" or "closing" state.

1. Check DLQ: `SELECT * FROM dead_letter WHERE operation LIKE 'trade%' AND status='pending';`
2. Check Bybit API status: `GET /api/v1/health` → `coingecko` field.
3. Manual resolution: Update trade status via SQL if exchange confirms execution.
4. Retry: `POST /api/v1/trades/{id}/retry` (re-submits to exchange).

---

## 5. Deployment & Rollback

### Blue-Green Deployment

```bash
# Deploy new version
docker build -t tradingagents:v2.1.0 .
docker tag tradingagents:v2.1.0 registry/tradingagents:latest

# Health check new container before switching traffic
docker run -d --name ta-green -p 8001:8000 tradingagents:v2.1.0
curl -f http://localhost:8001/api/v1/healthz || { docker rm -f ta-green; exit 1; }

# Switch traffic (nginx/HAProxy/ALB)
# ... update upstream to :8001 ...

# Remove old container after drain
sleep 30 && docker rm -f ta-blue
```

### Rollback

```bash
# Immediate rollback (< 1 minute)
docker tag registry/tradingagents:previous registry/tradingagents:latest
# Redeploy previous image

# Database rollback (if migration was applied)
alembic downgrade -1
```

### Pre-deployment Checklist

- [ ] All CI checks pass (lint, typecheck, tests, build)
- [ ] Database migrations tested against production snapshot
- [ ] Secrets/env vars updated in target environment
- [ ] Monitoring dashboards open during deploy
- [ ] Rollback plan confirmed (previous image tagged, migration reversible)
