#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="wait-local-agent-integration"
TOKEN="${WAIT_COMPOSE_TEST_TOKEN:-integration-admin-token}"
CLIENT_ID="${WAIT_COMPOSE_TEST_CLIENT_ID:-browser-smoke}"
VAULT_KEY="${WAIT_COMPOSE_VAULT_KEY:-$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')}"
API_PORT="${WAIT_COMPOSE_API_PORT:-8788}"
UI_PORT="${WAIT_COMPOSE_UI_PORT:-5173}"
COMPOSE=(docker compose --project-name "$PROJECT" -f "$ROOT_DIR/docker-compose.yml")

cleanup() {
env WAIT_ADMIN_TOKEN="$TOKEN" WAIT_CLIENT_ID="$CLIENT_ID" WAIT_VAULT_KEY="$VAULT_KEY" WAIT_DEMO_MODE=false "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for the Compose integration test." >&2
  exit 2
fi

env WAIT_ADMIN_TOKEN="$TOKEN" WAIT_CLIENT_ID="$CLIENT_ID" WAIT_VAULT_KEY="$VAULT_KEY" WAIT_DEMO_MODE=false \
  WAIT_RATE_LIMIT_GENERAL=2000/minute WAIT_RATE_LIMIT_CONNECTOR=200/minute "${COMPOSE[@]}" up --build --detach

for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error \
    -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:$API_PORT/health" >/dev/null; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    echo "Compose API did not become healthy." >&2
    exit 1
  fi
  sleep 2
done

for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error "http://127.0.0.1:$UI_PORT/" | grep -q 'id="root"'; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    echo "Compose UI did not serve the Vite entrypoint." >&2
    exit 1
  fi
  sleep 2
done

if curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:$API_PORT/health" | grep -q '^200$'; then
  echo "Unauthenticated health unexpectedly succeeded." >&2
  exit 1
fi

echo "Compose integration passed: authenticated API health and UI availability verified."

if [[ "${WAIT_COMPOSE_RUN_BROWSER:-false}" == "true" ]]; then
  WAIT_BROWSER_TOKEN="$TOKEN" \
    WAIT_BROWSER_UI_URL="http://127.0.0.1:$UI_PORT" \
    WAIT_BROWSER_API_URL="http://127.0.0.1:$API_PORT" \
    npm --prefix "$ROOT_DIR/ui" run test:e2e
fi
