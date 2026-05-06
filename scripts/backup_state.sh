#!/usr/bin/env bash
set -euo pipefail

destination="${1:-.wait-local-agent/backups/state-$(date -u +%Y%m%dT%H%M%SZ).db}"
wait-local-agent backup create "$destination"
