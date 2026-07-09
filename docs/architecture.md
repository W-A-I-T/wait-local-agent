# Architecture

WAIT Local Agent is a local-first operator appliance composed of a small public core plus optional installed packs.

## Runtime

- FastAPI API served by `wait-local-agent serve`
- Typer CLI exposed as `wait-local-agent`
- React dashboard served through the Docker Compose Vite UI on port `5173`
- SQLite state store on the local filesystem or the appliance volume
- Docker Compose packaging for the API, UI, health checks, and persistent data

## Authentication and RBAC

- Bearer-token roles: viewer, technician, and admin
- Tokens configured through `WAIT_VIEWER_TOKEN`, `WAIT_TECH_TOKEN`, `WAIT_ADMIN_TOKEN`
- Legacy `WAIT_API_TOKEN` remains an admin-equivalent token
- Demo mode bypass for local walkthroughs when `WAIT_DEMO_MODE=true`
- Role enforcement on API surfaces through the RBAC module

## Data and Tenancy

- Tickets, approvals, workflow runs, audit events, knowledge documents, and scheduled jobs persist in SQLite
- Stored views accept `client_id` filters so operators can scope data per tenant
- Approval execution captures a hashed approver identifier instead of raw token material

## Knowledge and Ticket Intelligence

- Markdown, text, and text-based PDF ingest
- SQLite FTS5 search by default
- Optional Qdrant backend
- Deterministic summary path for offline demos and stable tests
- Optional local OpenAI-compatible inference endpoint for richer summaries when enabled

## Connectors

- HaloPSA read paths for tickets, notes, clients, assets, and categories
- HaloPSA write path modeled as local draft, approval review, and explicit execution
- Hudu read-only documentation context
- Connector credential validation through `wait-local-agent connectors validate ...`
- Outbound calls gated by `WAIT_ALLOW_HTTP_PROBING`
- Live writes gated by `WAIT_ALLOW_WRITE_ACTIONS`

## Workflow and Scheduler

- Fixed workflow template catalog in the public core
- Workflow runs persisted with status, message, and approval linkage
- APScheduler-backed scheduled jobs loaded from SQLite at startup
- Scheduled workflow routes mounted under `/scheduled-jobs`
- Pause, resume, delete, and audit tracking for scheduled jobs

## Secrets, Backup, and Audit

- Secret backends: plain env vars or local Fernet vault
- Encrypted backup and restore commands backed by a vault-stored `WAIT_BACKUP_FERNET_KEY`
- Immutable audit event stream for approvals, connector reads, connector execution, scheduler triggers, and workflow state changes
- Audit export in JSON or CSV from CLI and API

## Update Channel

- Optional signed release metadata checks
- Configured through `WAIT_UPDATE_CHANNEL_URL` and `WAIT_UPDATE_PUBKEYS`
- Exposed through `wait-local-agent update check` and `/update-status`

## Pack Loader and Founder Surface

- Pack discovery from importable `packs.*` modules and the top-level `sync` package
- `wait-local-agent packs list`, `status`, and `install` are part of the public core
- Signed tarball install requires `WAIT_PACK_SIGNING_SECRET`
- Licensed packs unlock with `WAIT_LICENSE_KEY`
- Founder routes and CLI are public contracts, but the real founder implementation lives in an installed pack
- When the founder pack is absent, founder API routes return `501` and CLI commands exit with an install hint
