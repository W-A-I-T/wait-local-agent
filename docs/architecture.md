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
- Scheduled workflow and ticket-agent routes mounted under `/scheduled-jobs`
- Pause, resume, delete, and audit tracking for scheduled jobs

## Bounded agents

- Agent definitions persist a short, explicit sequence of existing smart
  actions in SQLite.
- The first public agent mode is ticket-scoped. Definitions allow only
  registered tools, cap runs at eight steps and 120 seconds, and retain the
  configured client scope. Manual runs and persisted five-field cron schedules
  are supported.
- Each tool call delegates to `SmartActionService`, so existing approval,
  redaction, tenancy, and provider behavior is reused rather than duplicated.
- Agent runs are grouped in the existing execution observability tables with
  one redacted step record per tool. Authenticated event deliveries use the
  same runtime, deterministic filters, tenant scope, idempotency keys, and
  run-once-per-entity protection. Definition changes create immutable redacted
  revision snapshots; rollback validates a prior snapshot and persists it as a
  new version. Revision diffs are field-level and redacted, and each run records
  the definition version used. Event agents can depend on same-tenant agents; the dispatcher
  applies cycle prevention at definition time and waits for upstream completion
  with a bounded sequential pass. Each run also persists and returns a
  redacted operational final result containing the last tool status, output,
  evidence, and error detail; it contains no hidden reasoning. Backfills and
  conversational agents remain future extensions.

## Template gallery

The local gallery stores provenance-bearing copies of the fixed core workflow
catalog. Gallery entries retain the source template identity and tenant scope;
execution resolves back to the reviewed core implementation, so the gallery
does not create an unrestricted code or prompt execution surface.

## Backfills

Backfills are persisted, sequential batches of existing bounded agent runs. The
controller caps a request at 100 ticket IDs, records each run and failure, and
supports queued/paused/completed/cancelled state plus failed-item reruns. It
does not introduce parallel execution or bypass the normal agent, approval,
redaction, or tenant checks.

## Event-triggered agents

- `POST /automation/events` accepts supported ticket events with an
  `Idempotency-Key` header or request-body key.
- Event definitions use `trigger: "event"` and deterministic filters such as
  `{"event_type": "ticket.created", "priority": "P1"}`.
- Deliveries persist redacted payloads, matched definitions, run IDs, status,
  errors, and tenant scope in SQLite. Duplicate keys do not execute again.

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
