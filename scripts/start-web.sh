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

# Container bind. Default 0.0.0.0 is correct INSIDE a container: Docker forwards the
# published host port to the container's eth0, never to container-loopback, so a
# 127.0.0.1 in-container bind would be unreachable. This is NOT the exposure boundary
# — that is docker-compose's host-side port map (TRADINGAGENTS_HOST_BIND, default
# 127.0.0.1). Passed as the real argv token below so the backend reports the true bind.
BIND_HOST="${TRADINGAGENTS_BIND_HOST:-0.0.0.0}"
PORT="${TRADINGAGENTS_PORT:-8877}"

BACKEND_CMD=(
  python
  -m
  uvicorn
  backend.main:create_app
  --host
  "$BIND_HOST"
  --port
  "$PORT"
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
npm run dev -- --host "$BIND_HOST" --port 5177 --strictPort &
FRONTEND_PID="$!"

echo "========================================"
echo "  TradingAgents Web UI"
echo "  Bind host   : $BIND_HOST (container-internal; host exposure = compose port map)"
echo "  Backend API : http://localhost:$PORT"
echo "  Frontend    : http://localhost:5177"
echo "========================================"
echo

wait -n "$BACKEND_PID" "$FRONTEND_PID"
