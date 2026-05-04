#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${TRADINGAGENTS_DEPLOY_ROOT:-$ROOT_DIR}"
WEB_ROOT="${TRADINGAGENTS_WEB_ROOT:-/var/www/tradingagents}"
SERVICE_NAME="${TRADINGAGENTS_SERVICE_NAME:-tradingagents}"
HEALTHCHECK_URL="${TRADINGAGENTS_HEALTHCHECK_URL:-}"
HEALTHCHECK_RETRIES="${TRADINGAGENTS_HEALTHCHECK_RETRIES:-24}"
HEALTHCHECK_DELAY="${TRADINGAGENTS_HEALTHCHECK_DELAY:-5}"
PYTHON_BIN="${TRADINGAGENTS_PYTHON_BIN:-python3}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd "$PYTHON_BIN"
require_cmd npm
require_cmd rsync
require_cmd curl

cd "$APP_DIR"

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e .

pushd frontend >/dev/null
npm ci
npm run build
popd >/dev/null

sudo rsync -a --delete "$APP_DIR/frontend/dist/" "$WEB_ROOT/"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl reload nginx

if [[ -n "$HEALTHCHECK_URL" ]]; then
  for ((attempt = 1; attempt <= HEALTHCHECK_RETRIES; attempt++)); do
    if curl --fail --silent --show-error "$HEALTHCHECK_URL" >/dev/null; then
      break
    fi

    if [[ "$attempt" -eq "$HEALTHCHECK_RETRIES" ]]; then
      echo "Health check failed after ${HEALTHCHECK_RETRIES} attempts." >&2
      exit 1
    fi

    sleep "$HEALTHCHECK_DELAY"
  done
fi

echo "Deployment complete."
