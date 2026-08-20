# Docker Quickstart

WAIT Local Agent ships as a Docker Compose appliance with:

- FastAPI API on `8788`
- Vite-proxied dashboard on `5173`
- SQLite state in the `wait-local-agent-data` volume

The compose stack is local-first by default. Non-demo startup requires an
admin credential; connector probing, live writes, encrypted backups, paid
packs, and update checks remain explicit opt-ins.

## Requirements

- Docker with Compose support
- Git
- Optional Python 3.12 environment if you want to run host-side CLI commands
- Optional secrets manager for storing the `.env` file outside the repo

## Install

### Helper

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/main/scripts/install.sh | bash
```

The helper:

1. Clones the repository if needed.
2. Copies `.env.example` to `.env` when `.env` is missing.
3. Starts `docker compose up --build`.

Without a `.env` file, Compose uses `WAIT_DEMO_MODE=false`; provide an admin
credential or explicitly set `WAIT_DEMO_MODE=true` for the bounded local demo.

### Manual

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
cp .env.example .env
docker compose up --build
```

Open:

- Dashboard: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8788`

The dashboard is the Vite UI. API requests are proxied from the dashboard container to the API container.

`scripts/install.sh` generates `.env` from `.env.example` when it is missing.
It does not enable demo mode or load `.env` for host-side CLI commands.

## Production `.env` Setup

Start from `.env.example` and fill in only the values you need. For a production-style appliance, at minimum set:

```text
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=
WAIT_ADMIN_TOKEN=<strong-local-admin-token>
WAIT_TECH_TOKEN=
WAIT_VIEWER_TOKEN=
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=/data/vault
WAIT_RATE_LIMIT_ENABLED=true
WAIT_RATE_LIMIT_GENERAL=100/minute
WAIT_RATE_LIMIT_CONNECTOR=10/minute
WAIT_SCHEDULER_ENABLED=true
```

Role guidance:

- `WAIT_API_TOKEN` is the legacy admin-equivalent token.
- `WAIT_ADMIN_TOKEN` is the preferred admin token.
- `WAIT_TECH_TOKEN` should be used for approval execution and workflow operations.
- `WAIT_VIEWER_TOKEN` is for read-only dashboard/API access.
- An active persisted principal credential with the global `msp_admin` role can
  be used instead of an environment admin token.

Non-demo startup fails unless an admin credential is configured. Explicit demo
mode disables provider writes and deployments and returns HTTP 403 from
`/secrets`.

## Secrets Vault

For production-style installs, keep connector secrets and the backup encryption key out of shell history. The shipped vault flow is:

```bash
docker compose exec api wait-local-agent secrets init
docker compose exec api wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
docker compose exec api wait-local-agent secrets set WAIT_HUDU_API_KEY '<secret>'
```

For a non-demo deployment using an external secret manager, set
`WAIT_VAULT_KEY` in the container environment before initializing the vault.
The vault then uses that Fernet key without creating `vault.key` beside the
encrypted secrets file. Do not add it to an existing local-key vault unless
the secrets have been migrated to the external key; otherwise the old
ciphertext cannot be decrypted.

To enable encrypted backups, also store a Fernet key:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
docker compose exec api wait-local-agent secrets set WAIT_BACKUP_FERNET_KEY '<generated-fernet-key>'
```

## Encrypted Backup Schedule

The shipped backup commands are:

```bash
docker compose exec api wait-local-agent backup create /data/backups/state.db.enc --encrypt
docker compose exec api wait-local-agent backup restore /data/backups/state.db.enc --encrypted
```

Requirements:

- `WAIT_SECRETS_BACKEND=fernet`
- initialized vault at `WAIT_VAULT_PATH`
- `WAIT_BACKUP_FERNET_KEY` stored in the vault
- backup source and destination paths remain under the persistent `/data` volume

Suggested host cron example:

```cron
0 3 * * * cd /path/to/wait-local-agent && docker compose exec -T api wait-local-agent backup create /data/backups/state-$(date +\%F).db.enc --encrypt
```

Backups written under `/data/...` land in the API container's persistent volume.

## Connectors in Production

For connector reads, set:

```text
WAIT_ALLOW_HTTP_PROBING=true
```

For live HaloPSA writes, also set:

```text
WAIT_ALLOW_WRITE_ACTIONS=true
```

Then validate credentials before you rely on the integration:

```bash
docker compose exec api wait-local-agent connectors validate halopsa
docker compose exec api wait-local-agent connectors validate hudu
```

## Scheduled Workflows

The scheduler is enabled by default with:

```text
WAIT_SCHEDULER_ENABLED=true
```

Operational surfaces:

- `GET /scheduled-jobs`
- `POST /scheduled-jobs`
- `POST /scheduled-jobs/{job_id}/pause`
- `POST /scheduled-jobs/{job_id}/resume`
- `DELETE /scheduled-jobs/{job_id}`

Scheduled jobs run stored workflow templates and preserve `client_id` when provided in the job params.

## Signed Update Channel

Update checks remain off until both values are set:

```text
WAIT_UPDATE_CHANNEL_URL=
WAIT_UPDATE_PUBKEYS=
```

Operator check:

```bash
docker compose exec api wait-local-agent update check
```

## Installing Paid Packs

The pack loader is public. Pack implementation is not.

Install a signed pack tarball with:

```bash
docker compose exec api wait-local-agent packs install /tmp/wait-pack-name.tar.gz --license <key>
```

Pack install requirements:

- `WAIT_PACK_SIGNING_SECRET` must be set.
- The tarball must have a matching `.sig` file beside it.
- Licensed packs unlock with `WAIT_LICENSE_KEY`.
- If the vault backend is enabled, `packs install --license` stores the key for you.

The license module required for unlock lives in the packs distribution. Installing the public repo alone does not provide proprietary pack logic.

## Founder Surface

The founder CLI and `/founder/*` routes are always present in the public contract. Real founder functionality still requires the founder pack to be installed.

Without the pack:

- CLI commands print an install hint and exit non-zero.
- `/founder/vault`, `/founder/preflight/latest`, `/founder/upload-preview/{artifact_id}`, `/founder/upload/{artifact_id}`, and related founder routes return `501`.

## Upgrade Notes

1. Pull the updated branch or release tag.
2. Review `.env.example` for new settings.
3. Preserve your `.env` and Docker volume.
4. Rebuild the appliance:

```bash
docker compose up --build
```

5. Run a quick health pass:

```bash
docker compose exec api wait-local-agent doctor
docker compose exec api wait-local-agent update check
```

If you use paid packs, keep `WAIT_PACK_SIGNING_SECRET`, `WAIT_LICENSE_KEY`, and any pack-specific secrets available before restarting.
