# Production Appliance Installation

The production appliance is a single versioned container image. FastAPI serves
both the API and the compiled dashboard, while a named Docker volume preserves
local state and encrypted vault data.

This guide is for Linux hosts used for an MSP or team installation. The
default listener is local-only at `127.0.0.1:8788`.

## Requirements

- Linux
- Docker Engine with the Compose v2 plugin
- `curl` or `wget`
- cosign CLI 2.x or newer (required for the default image signature check)
- A host directory where `/opt/wait-local-agent` can be created, or a custom
  `WAIT_INSTALL_DIR`

The installer does not install Docker, build source code, or require Git.

## Install a published version

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/v2.0.0/scripts/install.sh \
  | bash -s -- --version 2.0.0
```

The installer creates a private `.env`, generates a Fernet vault key and a
bootstrap administrator token, downloads `docker-compose.prod.yml` from the
same release tag, pulls the image, records its immutable digest as
`WAIT_IMAGE_REF`, verifies its keyless cosign signature, and starts it. The
bootstrap token is persisted in `.env` and printed at the end; store it in a
password manager immediately. The installer requires cosign CLI 2.x or newer;
the release workflow currently installs cosign 3.0.6 through
`sigstore/cosign-installer` v4.1.2.

If cosign cannot be installed, the default is to stop before starting the
appliance. An explicit exception is available for a controlled environment:

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/v2.0.0/scripts/install.sh \
  | bash -s -- --version 2.0.0 --no-verify
```

This logs the bypass and records `WAIT_IMAGE_VERIFIED=false` in `.env`.

Preview the actions without changing the host:

```bash
WAIT_INSTALL_DIR=/srv/wait-local-agent \
  bash scripts/install.sh --version 2.0.0 --dry-run
```

## First access and configuration

Open the printed local URL, then use the bootstrap administrator token when the
dashboard asks for access. The production Compose file passes only the
bootstrap settings needed by the appliance and keeps its data in the
`wait-local-agent-data` named volume.

To place a reverse proxy in front, override the host bind and trusted hosts in
`/opt/wait-local-agent/.env`, for example:

```text
WAIT_COMPOSE_API_PORT=8788
WAIT_TRUSTED_HOSTS=127.0.0.1,localhost,wait.example.com
```

The production Compose file sets `WAIT_SESSION_COOKIE_SECURE=true`. If a
non-localhost reverse proxy deliberately serves plain HTTP, set
`WAIT_SESSION_COOKIE_SECURE=false` in `.env`; otherwise browsers reject the
Secure session cookie and browser login silently fails. Use HTTPS for any
internet-facing deployment.

Keep the container listener private and terminate TLS at the reverse proxy.
Do not publish the Compose port on `0.0.0.0` unless the host firewall and proxy
policy have been reviewed.

### Caddy example

```caddyfile
wait.example.com {
    reverse_proxy 127.0.0.1:8788
}
```

Caddy obtains and renews the public certificate. Set
`WAIT_TRUSTED_HOSTS` to include the hostname used by the proxy, and protect the
dashboard with the administrator, technician, or viewer credentials appropriate
for each operator.

Reverse proxies must forward the browser's `Accept` header unchanged. They must
not cache HTML responses from the appliance: SPA navigation responses are marked
`Cache-Control: no-store` and `Vary: Accept`, while JSON API requests explicitly
request `application/json`. Preserve those headers when configuring proxy
caching so a cached dashboard document cannot be returned to an API request.
The proxy must not add CORS headers, including
`Access-Control-Allow-Origin`, for the dashboard origin. It must also pass the
dashboard's `X-WAIT-CSRF` header unchanged on cookie-authenticated state
changes.

## Backups

The SQLite state and vault live under `/data` in the named volume. Use the
[backups and vault guide](../operations/backups-and-vault.md) for encrypted
backup setup and restore exercises. Back up the volume or use the appliance's
backup commands before upgrades and before changing credentials.

## Upgrade

Re-run the installer from the new release tag after backing up the data volume,
passing the release explicitly with `--version`; it preserves existing
credentials and updates the digest-pinned image reference:

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/v2.0.1/scripts/install.sh \
  | WAIT_INSTALL_DIR=/opt/wait-local-agent bash -s -- --version 2.0.1
```

Do not edit only `WAIT_IMAGE_TAG`: the digest in `WAIT_IMAGE_REF` is the image
that Compose starts, and an explicit installer run is the upgrade operation.
The normal upgrade verifies the digest-pinned image with cosign and stops if
cosign is unavailable or verification fails. `--no-verify` bypasses only that
signature check, keeps the immutable digest pin, logs the exception, and writes
`WAIT_IMAGE_VERIFIED=false`; use it only in a controlled environment and record
the exception.

The named volume is not removed by `docker compose down`; do not add
`--volumes` unless you intentionally want to delete the appliance state.

## Development and desktop alternatives

Contributors should use the [Docker development quickstart](quickstart-docker.md#2-development-stack-source-and-vite-contributors),
which builds from a checkout and runs Vite. The [desktop installation](desktop-install.md)
is a separate non-MSP local surface.
