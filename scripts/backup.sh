#!/usr/bin/env bash
# Database backup script for TradingAgents.
# Usage: ./scripts/backup.sh [--verify]
# Requires: pg_dump, DATABASE_URL env var.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups/tradingagents}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="$BACKUP_DIR/full_${TIMESTAMP}.dump"

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL environment variable is required" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Starting backup to $DUMP_FILE ..."
pg_dump "$DATABASE_URL" \
    --format=custom \
    --compress=9 \
    --file="$DUMP_FILE"

SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo "Backup completed: $DUMP_FILE ($SIZE)"

# Verify backup integrity if requested
if [ "${1:-}" = "--verify" ]; then
    echo "Verifying backup integrity..."
    pg_restore --list "$DUMP_FILE" > /dev/null
    echo "Verification passed."
fi

# Prune backups older than retention period
PRUNED=$(find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION_DAYS -print -delete | wc -l)
if [ "$PRUNED" -gt 0 ]; then
    echo "Pruned $PRUNED backup(s) older than $RETENTION_DAYS days."
fi
