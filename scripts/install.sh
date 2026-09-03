#!/usr/bin/env bash
set -euo pipefail

version="stable"
dry_run=false
no_verify=false
install_dir="${WAIT_INSTALL_DIR:-/opt/wait-local-agent}"
image_repo="ghcr.io/w-a-i-t/wait-local-agent"
api_port="${WAIT_COMPOSE_API_PORT:-8788}"

usage() {
  cat <<'EOF'
Usage: install.sh [--version X.Y.Z|stable] [--dry-run] [--no-verify]

Install the published WAIT Local Agent production appliance. Docker is not
installed automatically; install Docker Engine with the Compose v2 plugin first.
By default, the pulled image is verified with cosign; --no-verify is an explicit,
logged override for environments that cannot install cosign.
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
    --no-verify)
      no_verify=true
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
if [[ -e "$install_dir/.env" && ! -f "$install_dir/.env" ]]; then
  echo "$install_dir/.env is not a regular file" >&2
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

download() {
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --location "$1"
  else
    wget --no-verbose --output-document=- "$1"
  fi
}

if [[ "$version" == "stable" ]]; then
  release_json="$(download "https://api.github.com/repos/W-A-I-T/wait-local-agent/releases/latest")" || {
    echo "could not resolve stable to the latest GitHub release" >&2
    exit 1
  }
  release_tag="$(printf '%s' "$release_json" | sed -n 's/.*"tag_name":[[:space:]]*"\(v[0-9][^"]*\)".*/\1/p' | head -n 1)"
  if [[ -z "$release_tag" ]]; then
    echo "GitHub releases API returned no valid latest release tag" >&2
    exit 1
  fi
  version="${release_tag#v}"
  printf 'Resolved stable to release %s.\n' "$release_tag" >&2
fi

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "resolved release is not a semantic version: $version" >&2
  exit 1
fi

mkdir -p "$install_dir/data"
chmod 700 "$install_dir" "$install_dir/data"

image="${image_repo}:${version}"
compose_source="https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/v${version}/docker-compose.prod.yml"
download "$compose_source" >"$install_dir/docker-compose.prod.yml"

docker pull "$image"
image_ref="$(docker image inspect --format '{{index .RepoDigests 0}}' "$image")"
image_digest="${image_ref#*@}"
if [[ "$image_ref" != "$image_repo@$image_digest" || ! "$image_digest" =~ ^sha256:[a-fA-F0-9]{64}$ ]]; then
  echo "could not determine a valid registry digest for $image" >&2
  exit 1
fi

image_verified=true
if [[ "$no_verify" == true ]]; then
  echo "WARNING: --no-verify bypasses signature verification for $image_ref; record and review this exception." >&2
  image_verified=false
else
  if ! command -v cosign >/dev/null 2>&1; then
    echo "cosign (version 2.x or newer) is required to verify the image; install cosign or rerun with --no-verify" >&2
    exit 1
  fi
  if ! cosign verify \
    --certificate-identity-regexp '^https://github.com/W-A-I-T/wait-local-agent/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    "$image_ref"; then
    echo "cosign signature verification failed for $image_ref" >&2
    exit 1
  fi
fi

existing_env=false
if [[ -f "$install_dir/.env" ]]; then
  existing_env=true
fi

if [[ "$existing_env" != true ]]; then
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
WAIT_IMAGE_REF=$image_ref
WAIT_IMAGE_VERIFIED=$image_verified
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
else
  umask 077
  env_tmp="$(mktemp "$install_dir/.env.XXXXXX")"
  awk -v image_tag="$version" -v image_ref="$image_ref" -v image_verified="$image_verified" '
    BEGIN { updated_tag = 0; updated_ref = 0; updated_verified = 0 }
    /^WAIT_IMAGE_TAG=/ { print "WAIT_IMAGE_TAG=" image_tag; updated_tag = 1; next }
    /^WAIT_IMAGE_REF=/ { print "WAIT_IMAGE_REF=" image_ref; updated_ref = 1; next }
    /^WAIT_IMAGE_VERIFIED=/ { print "WAIT_IMAGE_VERIFIED=" image_verified; updated_verified = 1; next }
    { print }
    END {
      if (!updated_tag) print "WAIT_IMAGE_TAG=" image_tag
      if (!updated_ref) print "WAIT_IMAGE_REF=" image_ref
      if (!updated_verified) print "WAIT_IMAGE_VERIFIED=" image_verified
    }
  ' "$install_dir/.env" >"$env_tmp"
  chmod 600 "$env_tmp"
  mv "$env_tmp" "$install_dir/.env"
  admin_token="$(sed -n 's/^WAIT_ADMIN_TOKEN=//p' "$install_dir/.env" | head -n 1)"
fi

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
printf 'Bootstrap admin token (persisted in .env; rotate after creating a database admin): %s\n' "$admin_token"
