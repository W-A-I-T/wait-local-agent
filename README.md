# WAIT Local Agent

[![CI](https://github.com/W-A-I-T/wait-local-agent/actions/workflows/test.yml/badge.svg)](https://github.com/W-A-I-T/wait-local-agent/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/W-A-I-T/wait-local-agent)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)

**Local-first MSP and founder automation appliance for tickets, runbooks, approvals, connector drafts, scheduled workflows, and auditable local operations.**

See the [capability roadmap](ROADMAP.md) and [NeoAgent parity matrix](docs/neoagent-parity-matrix.md) for the honest status of local-first MSP capabilities and the rationale for deferred work.

WAIT Local Agent is an Apache 2.0 self-hosted runtime with a FastAPI API, Typer CLI, React dashboard, SQLite state, signed update checks, and an open-core pack loader. The public repository ships the appliance surface; paid or proprietary pack implementation stays outside this repo.

> Safety default: fresh installs are read-first and local-first. Live connector writes require `WAIT_ALLOW_WRITE_ACTIONS=true`, outbound connector connection checks must be explicitly enabled, and HaloPSA writes still require an approved draft.

## What Ships In 1.0.0

- FastAPI API on port `8788`, React dashboard on port `5173`, and `wait-local-agent` CLI.
- Role-based bearer tokens with `WAIT_ADMIN_TOKEN`, `WAIT_TECH_TOKEN`, `WAIT_VIEWER_TOKEN`, plus legacy `WAIT_API_TOKEN` as an admin-equivalent token.
- Demo mode: when `WAIT_DEMO_MODE=true` and no role token is enforced, local demo flows run without bearer auth.
- SQLite-backed tickets, approvals, workflow runs, audit events, knowledge documents, and scheduled jobs.
- Client tenancy filters on stored surfaces such as `/tickets`, `/approval-requests`, `/audit`, `/audit-events/export`, `/workflow-runs`, `/knowledge/documents`, and `/scheduled-jobs`.
- HaloPSA read paths, approval-gated write drafts, and execution history.
- ConnectWise PSA read-only ticket and company lookup with explicit HTTP
  probing opt-in; no ConnectWise mutation path is enabled.
- Hudu read-only documentation context.
- A preview-only communication draft tool for email, Microsoft Teams, Slack,
  and SMS. Drafts are tenant-scoped, require technician approval, and never
  send network traffic in the public core.
- Connector credential validation with `wait-local-agent connectors validate halopsa`, `hudu`, or `connectwise`.
- Encrypted backup and restore with `wait-local-agent backup create --encrypt` and `wait-local-agent backup restore --encrypted`.
- Scheduled workflow and ticket-agent APIs under `/scheduled-jobs`, including
  UTC cron, interval, and future one-time schedules plus pause, resume,
  tenant-scoped reschedule, cancel/delete, linked ticket or agent targets, and
  auditable schedule history.
- Bounded agent definitions under `/agents`, an existing-tool catalog under
  `/tools` including read-only local knowledge search, ticket-quality and
  deterministic sentiment/escalation checks, collector previews, a
  technician-gated Microsoft 365 identity lookup over collected read-only
  inventory, and a bounded read-only RMM device lookup over collected
  endpoint-agent inventory, plus tenant-scoped HaloPSA ticket and Hudu
  documentation read tools,
  tenant-scoped ticket runs, and approval pause/resume. Agents may
  run manually, on a persisted five-field cron schedule, or from authenticated
  deterministic event deliveries with idempotency and run-once-per-entity
  protection. Active runs can be cancelled through `/agent-runs/{id}/cancel`,
  which also revokes a pending smart-action approval. Failed and cancelled
  runs can be retried with a persisted three-retry cap; conversational and
  unrestricted execution remain outside this slice. Run responses include a
  redacted operational final result for the last tool, including status,
  output, evidence, and error detail, without persisting hidden reasoning.
- Event-triggered agent APIs under `/automation/events` and
  `/automation/event-deliveries`, with deterministic filters, redacted payloads,
  tenant checks, and auditable delivery history.
- Agent revision history, redacted revision diffs, run-to-version links, and
  bounded rollback under `/agents/{id}/revisions`, with immutable snapshots and
  tenant-scoped restore-as-new-version. Agent run history also exposes the
  exact revision snapshot and supports approval-safe cancel and bounded retry
  controls under `/agent-runs`.
- Event agents may declare same-tenant dependencies; matching chains execute in
  deterministic bounded order and unmet upstream work is recorded as a failed
  delivery.
- A provenance-bearing local template gallery can copy reviewed core workflows
  into tenant-scoped records and run them through the existing approval path.
- Bounded agent backfills under `/agent-backfills` persist progress, counts,
  failures, pause/cancel state, and failed-item reruns.
- Signed update checks with `wait-local-agent update check`.
- Pack discovery plus `wait-local-agent packs list`, `status`, and `install`.
- Founder CLI and `/founder/*` routes in the public contract, returning stable `501` responses when the founder pack is not installed.

## Requirements

- Python 3.12+
- Docker with Compose support for the appliance path
- Node.js 22 only if you want to run the dashboard outside Docker
- Optional `uv` for contributor setup

## Download & install (desktop app)

For a guided local workspace with no Docker or terminal setup, download the
installer for Windows, macOS, or Linux from the latest GitHub Release. The app
keeps your workspace on this computer, starts the local service when it opens,
and closes it with the app.

Release signing is optional. Until the repository's signing secrets are
configured, your operating system may show a first-launch unsigned-app warning.
Confirm that the installer came from the WAIT Local Agent GitHub Release before
opening it. macOS releases include separate native installers for Intel and
Apple Silicon. See
[desktop-install.md](docs/desktop-install.md) for signing secrets, local builds,
and platform-specific notes.

## Quick Start

### Appliance path

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
cp .env.example .env
docker compose up --build
```

- Dashboard: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8788`
- The dashboard is a Vite dev server that proxies API traffic to the API container.
- Persistent SQLite state lives in the `wait-local-agent-data` Docker volume.
- `scripts/install.sh` generates `.env` from `.env.example` when it is missing.
- Demo mode still works without a `.env`; Compose falls back to the built-in demo-safe defaults in `docker-compose.yml`.
- Linux collectors are container-scoped by default. Host collection is an explicit, security-sensitive opt-in; see [host-collection.md](docs/host-collection.md).

The installer helper does the same clone/copy/start flow:

```bash
scripts/install.sh
```

or:

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/main/scripts/install.sh | bash
```

### Local CLI path

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
wait-local-agent doctor
```

Deterministic demo path:

```bash
scripts/demo_appliance.sh
```

Manual CLI checks against the shipped surface:

```bash
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1002
wait-local-agent workflows templates
wait-local-agent workflows run documentation-assisted-response TCK-1002
wait-local-agent approvals list
wait-local-agent events list
wait-local-agent connectors validate halopsa
wait-local-agent connectors validate hudu
wait-local-agent connectors connectwise-health
wait-local-agent connectors connectwise-tickets
wait-local-agent connectors connectwise-companies
wait-local-agent update check
wait-local-agent packs status
```

Cloud inventory connectors are governed read-only adapters for AWS, Azure,
GCP, and Microsoft 365. They require a vault credential reference and never
persist credential material. See the provider-specific permission guides:

- [AWS](docs/cloud-permissions-aws.md)
- [Azure](docs/cloud-permissions-azure.md)
- [GCP](docs/cloud-permissions-gcp.md)
- [Microsoft 365](docs/cloud-permissions-m365.md)

## Authentication and Demo Mode

Demo mode keeps local walkthroughs simple:

```text
WAIT_DEMO_MODE=true
WAIT_API_TOKEN=
WAIT_ADMIN_TOKEN=
WAIT_TECH_TOKEN=
WAIT_VIEWER_TOKEN=
```

For any shared LAN, appliance, or production-style install, disable demo mode and set role tokens:

```bash
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=<legacy-admin-token>
WAIT_ADMIN_TOKEN=<admin-token>
WAIT_TECH_TOKEN=<tech-token>
WAIT_VIEWER_TOKEN=<viewer-token>
```

Behavior:

- `WAIT_API_TOKEN` is the legacy admin-equivalent token.
- `WAIT_ADMIN_TOKEN` grants admin routes.
- `WAIT_TECH_TOKEN` grants technician routes.
- `WAIT_VIEWER_TOKEN` grants read-only routes.
- When `WAIT_DEMO_MODE=true`, requests resolve as local admin for demo use.

## Configuration

The complete shipped env surface is documented in [.env.example](.env.example). High-signal settings:

```text
WAIT_DATA_PATH=.wait-local-agent/state.db
WAIT_ALLOWED_DOC_ROOT=examples/sample_docs
WAIT_SECRETS_BACKEND=env
WAIT_VAULT_PATH=.wait-local-agent/vault
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
WAIT_VECTOR_BACKEND=sqlite
WAIT_CONNECTOR_TIMEOUT_SECONDS=20
WAIT_SCHEDULER_ENABLED=true
WAIT_RATE_LIMIT_ENABLED=true
WAIT_RATE_LIMIT_GENERAL=100/minute
WAIT_RATE_LIMIT_CONNECTOR=10/minute
WAIT_UPDATE_CHANNEL_URL=
WAIT_UPDATE_PUBKEYS=
WAIT_LICENSE_KEY=
WAIT_LICENSE_SECRET=
WAIT_PACK_SIGNING_SECRET=
```

## Secrets Vault and Encrypted Backups

The default secrets backend is plain environment variables. For longer-lived appliances and encrypted backups, switch to the Fernet vault:

```bash
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=.wait-local-agent/vault
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
wait-local-agent secrets set WAIT_BACKUP_FERNET_KEY '<generated-fernet-key>'
wait-local-agent backup create .wait-local-agent/backups/state.db.enc --encrypt
wait-local-agent backup restore .wait-local-agent/backups/state.db.enc --encrypted
```

Notes:

- Encrypted backups require `WAIT_SECRETS_BACKEND=fernet`.
- `WAIT_BACKUP_FERNET_KEY` must exist in the local vault before `--encrypt` or `--encrypted` works.
- `wait-local-agent secrets list` prints key names only.

## Connectors

### HaloPSA

Required settings:

```text
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
```

Credential validation:

```bash
wait-local-agent connectors validate halopsa
```

Read commands:

```bash
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket HALO-1002
wait-local-agent connectors halopsa-notes HALO-1002
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-assets <client-id>
wait-local-agent connectors halopsa-categories
```

Write path:

```bash
wait-local-agent connectors draft-halopsa HALO-1002 add_note \
  --field note="Internal note ready for review"
wait-local-agent approvals show 1
wait-local-agent approvals edit-field 1 note="Reviewed by technician"
wait-local-agent approvals update 1 approved "approved by technician"
wait-local-agent connectors execute-halopsa 1
```

Live HaloPSA writes require:

- outbound connector connection checks explicitly enabled
- `WAIT_ALLOW_WRITE_ACTIONS=true`
- configured credentials
- a pending draft
- explicit approval

### Hudu

Required settings:

```text
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
```

Validation:

```bash
wait-local-agent connectors validate hudu
```

Read commands:

```bash
wait-local-agent connectors hudu-health
wait-local-agent connectors hudu-companies
wait-local-agent connectors hudu-articles
wait-local-agent connectors hudu-article ARTICLE-1
wait-local-agent connectors hudu-folders
```

Hudu is read-only in the public repo.

### ConnectWise PSA

Required settings:

```text
WAIT_CONNECTWISE_BASE_URL=
WAIT_CONNECTWISE_COMPANY=
WAIT_CONNECTWISE_PUBLIC_KEY=
WAIT_CONNECTWISE_PRIVATE_KEY=
WAIT_CONNECTWISE_CLIENT_ID=
WAIT_CONNECTWISE_API_VERSION=2022.1
```

Read commands are available through the CLI and the `/connectors/connectwise/*`
API routes. Set `WAIT_ALLOW_HTTP_PROBING=true` before any network request;
credentials are read from settings/vault and are never accepted in request
payloads. Writes are not implemented in the public core.

## Scheduled Workflows and Tenancy Filters

Workflow templates are listed with:

```bash
wait-local-agent workflows templates
```

Workflow runs and scheduled jobs are available over API routes, including:

- `GET /scheduled-jobs`
- `POST /scheduled-jobs`
- `POST /scheduled-jobs/{job_id}/pause`
- `POST /scheduled-jobs/{job_id}/resume`
- `POST /scheduled-jobs/{job_id}/reschedule`
- `DELETE /scheduled-jobs/{job_id}`

Use `template_id` for a workflow schedule. Use `agent_id` plus `entity_id` for
an agent schedule; the agent definition must use the `scheduled` trigger and
the job's `params.input` object is passed to the bounded executor.

Stored API views accept `client_id` filters where applicable so operators can scope tickets, approvals, audit events, workflow runs, knowledge documents, and scheduled jobs per tenant.

Communication previews are available through the `communication-draft` smart
action and `/tools` catalog. Supported channels are `email`, `teams`, `slack`,
and `sms`; the result is explicitly marked `delivery_mode: preview` and
`sendable: false` until a separately governed connector execution path exists.

## Updates

Signed update checks are disabled by default until both settings are populated:

```text
WAIT_UPDATE_CHANNEL_URL=
WAIT_UPDATE_PUBKEYS=
```

Check for updates:

```bash
wait-local-agent update check
```

## Packs and Founder Surface

Pack operations:

```bash
wait-local-agent packs list
wait-local-agent packs status
wait-local-agent packs install /path/to/wait-pack-name.tar.gz --license <key>
```

Pack notes:

- `WAIT_PACK_SIGNING_SECRET` is required to install a signed tarball.
- `WAIT_LICENSE_KEY` unlocks licensed packs.
- When the Fernet vault is enabled, `packs install --license` stores the key in the vault; otherwise the CLI prints a reminder to set `WAIT_LICENSE_KEY` manually.
- `WAIT_LICENSE_SECRET` is loaded into config for pack-specific license flows but is not consumed by the public core directly.

Founder surface:

```bash
wait-local-agent founder scan /path/to/project
wait-local-agent founder preflight
wait-local-agent founder handoff --output handoff.md
wait-local-agent founder export-bundle --artifact-id art-1 --output bundle.json
wait-local-agent founder upload --artifact-id art-1 --yes
```

Public founder routes:

- `POST /founder/scan`
- `GET /founder/vault`
- `GET /founder/preflight/latest`
- `GET /founder/upload-preview/{artifact_id}`
- `POST /founder/upload/{artifact_id}`
- `GET /founder/lp-status`

If the founder pack is absent, founder CLI commands exit with an install hint and founder API routes return `501` with `{"error":"founder pack not installed"}`.

## More Documentation

- [docs/appliance-install.md](docs/appliance-install.md)
- [docs/connector-setup.md](docs/connector-setup.md)
- [docs/local-demo.md](docs/local-demo.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/security-model.md](docs/security-model.md)
- [docs/pack-loader.md](docs/pack-loader.md)
- [docs/update-channel.md](docs/update-channel.md)
- [docs/open-core-boundary.md](docs/open-core-boundary.md)
