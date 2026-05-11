#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

if [[ -z "${PYTHON:-}" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  export PATH="$ROOT_DIR/.venv/bin:$PATH"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi

ruff check .
mypy src tests
bandit -r src
pip-audit --skip-editable
"$PYTHON_BIN" -m pytest --cov=wait_local_agent --cov-report=term-missing --cov-fail-under=95
"$PYTHON_BIN" scripts/public_surface_audit.py

cd "$ROOT_DIR/ui"
npm ci
npm run test
npm run build
