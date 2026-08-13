#!/usr/bin/env bash
set -euo pipefail

# Exercise the canonical consultant paths with every external and mutating
# capability explicitly denied. This is a local-first validation gate, not a
# provider or deployment smoke test.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v wait-local-agent >/dev/null 2>&1; then
  echo "wait-local-agent is required; install the repository package first" >&2
  exit 127
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/wait-local-agent-local-first.XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT

export WAIT_DATA_PATH="$WORK_DIR/state.db"
export WAIT_DEMO_MODE=true
export WAIT_OFFLINE_MODE=true
export WAIT_ALLOW_CLOUD_FALLBACK=false
export WAIT_ALLOW_HTTP_PROBING=false
export WAIT_ALLOW_LLM_INFERENCE=false
export WAIT_ALLOW_WRITE_ACTIONS=false
export WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=false
export WAIT_REMOTE_MODEL_PROVIDER=openai-compatible
export WAIT_REMOTE_MODEL_BASE_URL=http://127.0.0.1:9/v1
export WAIT_REMOTE_MODEL_NAME=local-first-fixture
export WAIT_REMOTE_MODEL_API_KEY=local-first-fixture-key

health_output="$(wait-local-agent microsoft provider health)"
if [[ "$health_output" != *"status=blocked_offline"* ]]; then
  echo "provider health did not report blocked_offline" >&2
  printf '%s\n' "$health_output" >&2
  exit 1
fi

PYTHON="${PYTHON:-python3}" "$ROOT_DIR/scripts/demo_employee_onboarding.sh" >/dev/null
bash "$ROOT_DIR/scripts/demo_consultant_mode.sh" >/dev/null

echo "local-first validation passed: offline, no writes, no probing, no model inference"
