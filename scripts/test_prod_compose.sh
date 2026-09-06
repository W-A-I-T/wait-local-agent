#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="wait-local-agent-prod-integration"
IMAGE_TAG="ci"
IMAGE="ghcr.io/w-a-i-t/wait-local-agent:${IMAGE_TAG}"
TOKEN="${WAIT_PROD_COMPOSE_TEST_TOKEN:-integration-admin-token}"
PORT="${WAIT_PROD_COMPOSE_API_PORT:-18789}"
COMPOSE=(docker compose --project-name "$PROJECT" -f "$ROOT_DIR/docker-compose.prod.yml")
FIXTURE_CONFIG=""
VAULT_KEY=""

cleanup() {
  env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
    WAIT_SECRETS_BACKEND=fernet WAIT_VAULT_KEY="$VAULT_KEY" WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
    "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "$FIXTURE_CONFIG" ]]; then rm -f "$FIXTURE_CONFIG"; fi
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for the production Compose integration test." >&2
  exit 2
fi

# Use the production vault with an ephemeral key. The env backend is read-only
# and cannot exercise saving a connector through the real browser journey.
VAULT_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
if [[ "${WAIT_PROD_COMPOSE_RUN_BROWSER:-false}" == "true" ]]; then
  FIXTURE_CONFIG="$(mktemp)"
  cat >"$FIXTURE_CONFIG" <<'YAML'
services:
  api:
    environment:
      WAIT_RATE_LIMIT_GENERAL: 2000/minute
      WAIT_RATE_LIMIT_CONNECTOR: 200/minute
YAML
  COMPOSE+=(-f "$FIXTURE_CONFIG")
fi

env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=fernet WAIT_VAULT_KEY="$VAULT_KEY" WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
docker build --tag "$IMAGE" "$ROOT_DIR"

env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=fernet WAIT_VAULT_KEY="$VAULT_KEY" WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
  "${COMPOSE[@]}" up --detach --pull never

for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error "http://127.0.0.1:$PORT/healthz" >/dev/null; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    "${COMPOSE[@]}" logs --tail=50 api >&2 || true
    exit 1
  fi
  sleep 2
done

curl --fail --silent "http://127.0.0.1:$PORT/" | grep -q 'id="root"'

"${COMPOSE[@]}" exec -T api python -c \
  'from pathlib import Path; from wait_local_agent.store import Store; Store(Path("/data/state.db")).create_client("persisted", "Persisted")'

env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=fernet WAIT_VAULT_KEY="$VAULT_KEY" WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
  "${COMPOSE[@]}" down
env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=fernet WAIT_VAULT_KEY="$VAULT_KEY" WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
  "${COMPOSE[@]}" up --detach --pull never

for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error "http://127.0.0.1:$PORT/healthz" >/dev/null; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    exit 1
  fi
  sleep 2
done

curl --fail --silent --show-error \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/clients/persisted" | grep -q 'Persisted'
echo "Production Compose integration passed: health, SPA, and named-volume persistence verified."

if [[ "${WAIT_PROD_COMPOSE_RUN_BROWSER:-false}" == "true" ]]; then
  WAIT_BROWSER_TOKEN="$TOKEN" \
    WAIT_BROWSER_UI_URL="http://127.0.0.1:$PORT" \
    WAIT_BROWSER_API_URL="http://127.0.0.1:$PORT" \
    npm --prefix "$ROOT_DIR/ui" run test:e2e
fi
