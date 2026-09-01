#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="wait-local-agent-prod-integration"
IMAGE_TAG="ci"
IMAGE="ghcr.io/w-a-i-t/wait-local-agent:${IMAGE_TAG}"
TOKEN="${WAIT_PROD_COMPOSE_TEST_TOKEN:-integration-admin-token}"
PORT="${WAIT_PROD_COMPOSE_API_PORT:-18789}"
COMPOSE=(docker compose --project-name "$PROJECT" -f "$ROOT_DIR/docker-compose.prod.yml")

cleanup() {
  env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
    WAIT_SECRETS_BACKEND=env WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
    "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for the production Compose integration test." >&2
  exit 2
fi

env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=env WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
docker build --tag "$IMAGE" "$ROOT_DIR"

env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=env WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
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
  WAIT_SECRETS_BACKEND=env WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
  "${COMPOSE[@]}" down
env WAIT_IMAGE_TAG="$IMAGE_TAG" WAIT_ADMIN_TOKEN="$TOKEN" WAIT_API_TOKEN="" \
  WAIT_SECRETS_BACKEND=env WAIT_TRUSTED_HOSTS=127.0.0.1,localhost WAIT_COMPOSE_API_PORT="$PORT" \
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
