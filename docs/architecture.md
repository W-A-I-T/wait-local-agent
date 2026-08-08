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
- IT Glue read-only organization-scoped documentation context
- Confluence Cloud read-only page listing and detail through REST API v2
- SharePoint read-only site and drive-item metadata through Microsoft Graph
- Microsoft Graph read-only user identity lookup through the guarded HTTP boundary
- ConnectWise PSA read-only ticket and company lookup through a guarded,
  credential-isolated adapter; mutation endpoints are intentionally absent.
- Syncro read-only ticket and customer lookup through the same guarded,
  credential-isolated boundary; mutation endpoints are intentionally absent.
- ServiceNow read-only incident and company lookup through the same guarded,
  credential-isolated Table API boundary; mutation endpoints are intentionally absent.
- Autotask read-only ticket and company lookup through the same guarded,
  credential-isolated REST boundary; mutation endpoints are intentionally absent.
- Connector credential validation through `wait-local-agent connectors validate ...`
- Outbound calls gated by `WAIT_ALLOW_HTTP_PROBING`
- Live writes gated by `WAIT_ALLOW_WRITE_ACTIONS`
- Communication uses a shared preview-only provider boundary for email, Teams,
  Slack, and SMS. The public adapters return local drafts only; they do not
  make outbound requests or imply delivery.

## Workflow and Scheduler

- Fixed workflow template catalog in the public core
- Workflow runs persisted with status, message, and approval linkage
- APScheduler-backed scheduled jobs loaded from SQLite at startup
- Scheduled workflow and ticket-agent routes mounted under `/scheduled-jobs`
- UTC cron, interval, and future one-time schedules with pause, resume,
  tenant-scoped reschedule, delete, and audit tracking

## Bounded agents

- Agent definitions persist a short, explicit sequence of existing smart
  actions in SQLite.
- The first public agent mode is ticket-scoped. Definitions allow only
  registered tools, cap runs at eight steps and 120 seconds, and retain the
  configured client scope. Manual runs and persisted five-field cron schedules
  are supported.
- Each tool call delegates to `SmartActionService`, so existing approval,
  redaction, tenancy, and provider behavior is reused rather than duplicated.
- Existing HaloPSA ticket reads and Hudu article reads are also exposed through
  the same tool contract. The actions reuse the guarded connector clients,
  require an explicit local tenant scope, and never accept connector
  credentials in action payloads.
- The read-first Microsoft 365 identity tool searches tenant-scoped,
  previously collected `m365-user` inventory. The separate connector surface
  can perform bounded live Graph user reads with operator-supplied credentials;
  neither path accepts credentials through an action payload or exposes writes.
- The read-only RMM boundary currently normalizes tenant-scoped
  `endpoint-agent` collector assets through a local adapter. It exposes device
  lookup without remote control, remediation, or credential-bearing payloads.
- Communication drafts use the same smart-action contract, tenant scope,
  redaction, and approval pause as other proposed actions. Channel-specific
  preview adapters are deliberately non-sendable until a separately reviewed
  connector execution path is added.
- Agent runs are grouped in the existing execution observability tables with
  one redacted step record per tool. Authenticated event deliveries use the
  same runtime, deterministic filters, tenant scope, idempotency keys, and
  run-once-per-entity protection. Definition changes create immutable redacted
  revision snapshots; rollback validates a prior snapshot and persists it as a
  new version. Revision diffs are field-level and redacted, and each run records
  the definition version used. Approval-paused runs can be cancelled through
  the same approval path, and terminal failed/rejected/cancelled runs can be
  retried. Event agents can depend on same-tenant agents; the dispatcher
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
