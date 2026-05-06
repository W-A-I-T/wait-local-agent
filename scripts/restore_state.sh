#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: scripts/restore_state.sh <backup.db>" >&2
  exit 2
fi

wait-local-agent backup restore "$1"
