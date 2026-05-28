#!/bin/bash
set -euo pipefail

PROJECT_DIR="/root/projects/TradingAgents"
BRANCH="main"

echo "=== Deploying TradingAgents ==="

cd "$PROJECT_DIR"

echo "[1/6] Pulling latest code..."
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

echo "[2/6] Installing Python dependencies..."
source .venv/bin/activate
pip install -e . --quiet

echo "[3/6] Installing frontend dependencies..."
cd frontend
npm install --silent

echo "[4/6] Building frontend..."
npm run build
cd ..

echo "[5/7] Running database migrations..."
set -a; source .env; set +a
python -m backend.migrate

echo "[6/7] Restarting services..."
systemctl restart tradingagents-backend
systemctl restart tradingagents-frontend

echo "[7/7] Verifying services..."
sleep 5
if systemctl is-active --quiet tradingagents-backend && systemctl is-active --quiet tradingagents-frontend; then
    echo "=== Deploy successful ==="
else
    echo "=== Deploy FAILED ==="
    systemctl status tradingagents-backend --no-pager -l
    systemctl status tradingagents-frontend --no-pager -l
    exit 1
fi
