#!/usr/bin/env bash
set -euo pipefail

# Repository-owned browser smoke entrypoint. The Compose integration wrapper
# owns stack startup/teardown; Playwright owns browser assertions.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec npm --prefix "$ROOT_DIR/ui" run test:e2e
