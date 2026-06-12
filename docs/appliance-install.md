# Appliance Install

WAIT Local Agent is packaged as a self-hosted Docker Compose appliance with an API, dashboard, and persistent SQLite state volume.

## Requirements

- Docker with Compose support
- Git
- Optional local Python 3.12 environment for CLI-only development
- Optional Node.js 22 for dashboard development outside Docker

## One-command helper

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/main/scripts/install.sh | bash
```

The helper clones the repo, copies `.env.example` to `.env` when missing, and starts Docker Compose.

## Manual install

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
cp .env.example .env
docker compose up --build
```

## Services

| Service | Default URL | Purpose |
| --- | --- | --- |
| API | `http://127.0.0.1:8788` | FastAPI operator API |
| Dashboard | `http://127.0.0.1:5173` | Local approval and connector dashboard |
| SQLite | Docker volume `wait-local-agent-data` | Tickets, approvals, events, workflows, knowledge index |

## Safe defaults

The Compose path explicitly keeps these defaults:

```text
WAIT_DEMO_MODE=true
WAIT_SECRETS_BACKEND=env
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_HTTP_PROBING=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
```

For a shared LAN or production-style test, set `WAIT_DEMO_MODE=false` and a strong `WAIT_API_TOKEN` in `.env`, then restart the API container.

## Backup and restore

```bash
scripts/backup_state.sh
scripts/restore_state.sh .wait-local-agent/backups/state.db
```

Inside the Docker volume, the API uses `/data/state.db`. Use the CLI backup command from a host-side Python install or copy the volume state according to your Docker operations policy.

## Local-only model policy

The default provider is deterministic. Local model inference is disabled until `WAIT_ALLOW_LLM_INFERENCE=true` and a local OpenAI-compatible endpoint is configured. Cloud fallback remains disabled unless explicitly enabled by the operator.
