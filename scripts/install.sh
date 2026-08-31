#!/usr/bin/env bash
set -euo pipefail

version="stable"
dry_run=false
install_dir="${WAIT_INSTALL_DIR:-/opt/wait-local-agent}"
image_repo="ghcr.io/w-a-i-t/wait-local-agent"
api_port="${WAIT_COMPOSE_API_PORT:-8788}"

usage() {
  cat <<'EOF'
Usage: install.sh [--version X.Y.Z|stable] [--dry-run]

Install the published WAIT Local Agent production appliance. Docker is not
installed automatically; install Docker Engine with the Compose v2 plugin first.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      if [[ $# -lt 2 ]]; then
        echo "--version requires a value" >&2
        exit 2
      fi
      version="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$version" != "stable" && ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "version must be stable or a semantic version such as 2.0.0" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "WAIT Local Agent production appliance requires Linux; use the desktop bundle on macOS or Windows." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Engine with the Compose v2 plugin, then rerun this installer." >&2
  exit 1
fi

compose_version="$(docker compose version 2>/dev/null || true)"
if [[ ! "$compose_version" =~ Docker\ Compose\ version\ v?([0-9]+)\. ]]; then
  echo "Docker Compose v2 is required. Install or enable the Docker Compose plugin, then rerun this installer." >&2
  exit 1
fi
compose_major="${BASH_REMATCH[1]}"
if (( compose_major < 2 )); then
  echo "Docker Compose v2 or newer is required. Install or enable the Docker Compose plugin, then rerun this installer." >&2
  exit 1
fi

if [[ "$dry_run" == true ]]; then
  printf 'Dry run: validated Linux, Docker, and Compose v2.\n'
  printf 'Image tag: %s\n' "$version"
  printf 'Install directory: %s\n' "$install_dir"
  printf 'Setup URL: http://127.0.0.1:%s\n' "$api_port"
  printf 'Actions: create the install directory, generate bootstrap credentials, download docker-compose.prod.yml, pull, start, and health-check the appliance.\n'
  exit 0
fi

if [[ -L "$install_dir" || ( -e "$install_dir" && ! -d "$install_dir" ) ]]; then
  echo "install directory is not a normal directory: $install_dir" >&2
  exit 1
fi
if [[ -e "$install_dir/.env" ]]; then
  echo "$install_dir/.env already exists; refusing to rotate its credentials. Edit WAIT_IMAGE_TAG there for an upgrade." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  echo "curl or wget is required to download the production Compose file." >&2
  exit 1
fi

http_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error "$1" >/dev/null
  else
    wget --quiet --spider "$1"
  fi
}

mkdir -p "$install_dir/data"
chmod 700 "$install_dir" "$install_dir/data"

image="${image_repo}:${version}"
compose_source="https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/main/docker-compose.prod.yml"
if [[ "$version" != "stable" ]]; then
  compose_source="https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/v${version}/docker-compose.prod.yml"
fi

if command -v curl >/dev/null 2>&1; then
  curl --fail --silent --show-error --location --output "$install_dir/docker-compose.prod.yml" "$compose_source"
else
  wget --no-verbose --output-document="$install_dir/docker-compose.prod.yml" "$compose_source"
fi

docker pull "$image"
vault_key="$(docker run --rm "$image" python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
if [[ ! "$vault_key" =~ ^[A-Za-z0-9_-]{43}=$ ]]; then
  echo "could not generate a valid Fernet vault key from the published image" >&2
  exit 1
fi

if command -v openssl >/dev/null 2>&1; then
  admin_token="$(openssl rand -hex 32)"
else
  admin_token="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
fi
if [[ -z "$admin_token" ]]; then
  echo "could not generate the administrator token" >&2
  exit 1
fi

umask 077
cat >"$install_dir/.env" <<EOF
WAIT_IMAGE_TAG=$version
WAIT_DATA_PATH=/data/state.db
WAIT_ADMIN_TOKEN=$admin_token
WAIT_API_TOKEN=
WAIT_TECH_TOKEN=
WAIT_VIEWER_TOKEN=
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_KEY=$vault_key
WAIT_VAULT_PATH=/data/vault
WAIT_TRUSTED_HOSTS=127.0.0.1,localhost
EOF
chmod 600 "$install_dir/.env"

pushd "$install_dir" >/dev/null
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

health_url="http://127.0.0.1:${api_port}/healthz"
healthy=false
for attempt in $(seq 1 60); do
  if http_ok "$health_url"; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != true ]]; then
  echo "WAIT Local Agent did not become healthy at $health_url" >&2
  docker compose -f docker-compose.prod.yml ps >&2 || true
  docker compose -f docker-compose.prod.yml logs --tail=50 api >&2 || true
  popd >/dev/null
  exit 1
fi
popd >/dev/null

printf 'WAIT Local Agent is ready.\n'
printf 'URL: http://127.0.0.1:%s\n' "$api_port"
printf 'One-time admin token: %s\n' "$admin_token"
