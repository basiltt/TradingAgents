#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

BACKEND_CMD=(
  python
  -m
  uvicorn
  backend.main:create_app
  --host
  0.0.0.0
  --port
  8877
  --factory
)

if [[ "${TRADINGAGENTS_DISABLE_RELOAD:-0}" != "1" ]]; then
  BACKEND_CMD+=(
    --reload
    --reload-dir
    "$ROOT_DIR/backend"
    --reload-dir
    "$ROOT_DIR/tradingagents"
  )
fi

cd "$ROOT_DIR"
"${BACKEND_CMD[@]}" &
BACKEND_PID="$!"

cd "$ROOT_DIR/frontend"
npm run dev -- --host 0.0.0.0 --port 5177 --strictPort &
FRONTEND_PID="$!"

echo "========================================"
echo "  TradingAgents Web UI"
echo "  Backend API : http://localhost:8877"
echo "  Frontend    : http://localhost:5177"
echo "========================================"
echo

wait -n "$BACKEND_PID" "$FRONTEND_PID"
