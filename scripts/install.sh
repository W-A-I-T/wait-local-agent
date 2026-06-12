#!/usr/bin/env bash
set -euo pipefail

repo_url="${WAIT_LOCAL_AGENT_REPO:-https://github.com/W-A-I-T/wait-local-agent.git}"
install_dir="${WAIT_LOCAL_AGENT_DIR:-wait-local-agent}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if [[ ! -d "$install_dir/.git" ]]; then
  git clone "$repo_url" "$install_dir"
fi

cd "$install_dir"
if [[ ! -f .env ]]; then
  cp .env.example .env
fi

if docker compose version >/dev/null 2>&1; then
  docker compose up --build
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose up --build
else
  echo "Docker Compose is required" >&2
  exit 1
fi
