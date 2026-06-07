#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

if [[ -d "$ROOT_DIR/.venv" ]]; then
  # Use the local virtual environment automatically when present.
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi

# Resolve + EXPORT the bind contract so it is a real environment value (not just an
# argv token): any child that reads os.environ sees the same host/port the server
# binds. SECURITY: loopback by default — the trading endpoints have no auth, so
# exposing them on 0.0.0.0 lets any device on the network place real-money trades.
# Override with TRADINGAGENTS_BIND_HOST=0.0.0.0 ONLY behind a trusted network + an
# auth proxy.
export TRADINGAGENTS_BIND_HOST="${TRADINGAGENTS_BIND_HOST:-127.0.0.1}"
export TRADINGAGENTS_PORT="${TRADINGAGENTS_PORT:-8877}"

BACKEND_CMD=(
  python
  -m
  uvicorn
  backend.main:create_app
  --host
  "$TRADINGAGENTS_BIND_HOST"
  --port
  "$TRADINGAGENTS_PORT"
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
npm run dev -- --host "${TRADINGAGENTS_BIND_HOST:-127.0.0.1}" --port 5177 --strictPort &
FRONTEND_PID="$!"

echo "========================================"
echo "  TradingAgents Web UI"
echo "  Backend API : http://localhost:8877"
echo "  Frontend    : http://localhost:5177"
echo "========================================"
echo

wait -n "$BACKEND_PID" "$FRONTEND_PID"
