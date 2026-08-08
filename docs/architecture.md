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
- Microsoft Graph read-only user and group context lookup through the guarded
  HTTP boundary
- ConnectWise PSA ticket and company lookup plus an allowlisted,
  approval-gated ticket PATCH path through a guarded, credential-isolated
  adapter.
- Syncro read-only ticket and customer lookup through the same guarded,
  credential-isolated boundary; mutation endpoints are intentionally absent.
- ServiceNow read-only incident and company lookup through the same guarded,
  credential-isolated Table API boundary; mutation endpoints are intentionally absent.
- Autotask read-only ticket and company lookup through the same guarded,
  credential-isolated REST boundary; mutation endpoints are intentionally absent.
- Connector credential validation through `wait-local-agent connectors validate ...`
- Outbound calls gated by `WAIT_ALLOW_HTTP_PROBING`
- Live writes gated by `WAIT_ALLOW_WRITE_ACTIONS`
- Communication uses a shared preview and delivery provider boundary for local
  ticket notes, email, Teams, Slack, and SMS. Previews never make network
  requests. Delivery requires a smart-action approval plus both
  `WAIT_ALLOW_WRITE_ACTIONS=true` and `WAIT_ALLOW_HTTP_PROBING=true`; email
  uses configured SMTP and the other external channels use bounded webhook
  adapters. Provider response bodies are never returned or persisted.

## Workflow and Scheduler

- Fixed workflow template catalog in the public core, including tool-backed
  ticket-quality, sentiment, escalation, and similar-ticket review templates
- Tool-backed templates call the existing smart-action registry through a small
  executor contract, so workflow runs do not create a second tool engine
- Workflow runs persisted with status, message, and approval linkage
- APScheduler-backed scheduled jobs loaded from SQLite at startup
- Scheduled workflow and ticket-agent routes mounted under `/scheduled-jobs`
- Pause, resume, tenant-scoped reschedule, delete, and audit tracking for
  scheduled jobs
- Agent definitions may gate execution with validated `HH:MM` windows in an
  IANA timezone; overnight windows are supported and closed scheduled jobs are
  audited without creating a run.

## Bounded agents

- Agent definitions persist a short, explicit sequence of existing smart
  actions in SQLite.
- The first public agent mode is ticket-scoped. Definitions allow only
  registered tools, cap runs at eight steps and 120 seconds, and retain the
  configured client scope. Manual runs and persisted five-field cron schedules
  are supported. Optional execution windows are persisted with revisions and
  evaluated before direct or scheduled runs.
- Definitions may explicitly select bounded `ticket`, `client`, and local
  `knowledge` context sources. Selected context is tenant-scoped, capped and
  redacted, persisted with the operational run state, and passed to each
  existing tool call as data; it is never treated as executable instructions.
- Each tool call delegates to `SmartActionService`, so existing approval,
  redaction, tenancy, and provider behavior is reused rather than duplicated.
- Existing HaloPSA, ConnectWise PSA, Syncro, ServiceNow, and Autotask ticket
  reads, plus Hudu article and IT Glue document reads, are exposed through the
  same tool contract. The actions reuse the guarded connector clients, require
  an explicit local tenant scope, and never accept connector credentials in
  action payloads. Confluence and SharePoint tools return metadata only; they
  do not expose page bodies or file contents.
- The read-first Microsoft 365 identity tool searches tenant-scoped,
  previously collected `m365-user` inventory. The separate connector surface
  can perform bounded live Graph user, group, subscribed-license, mailbox-folder,
  and Intune managed-device reads with operator-supplied credentials, plus an
  approval-gated user creation path that resolves a temporary password only
  from the local vault at execution time, plus an approval-gated disable path
  that only sets `accountEnabled=false`. Credentials never enter action or
  approval payloads. Intune managed-device retirement is a separate
  approval-gated, strict-ID action; it does not expose wipe or delete. A
  separate approval-gated mailbox-settings action accepts only timezone,
  locale, date-format, and time-format fields; message contents and forwarding
  are not exposed. Group membership changes
  are a distinct strict-ID add/remove action using the same approval path.
- The RMM boundary normalizes tenant-scoped `endpoint-agent` collector assets
  and exposes a shared contract for device lookup, alerts, script metadata,
  script preview, execution lookup, and approval-aware execution. The local
  adapter has no live alert/script source and blocks execution. The NinjaOne
  adapter uses an explicit WAIT-to-NinjaOne organization map, filters returned
  inventory to that organization, and implements the same contract without
  accepting credentials or provider scope IDs in action payloads.
- Communication drafts and delivery use the same smart-action contract, tenant
  scope, redaction, and approval pause as other proposed actions. Local ticket
  notes are persisted only for an existing tenant-scoped ticket; external
  adapters require explicit configuration and remain unavailable on a fresh
  install.
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
  evidence, and error detail; it contains no hidden reasoning. Conversational
  agents remain a future extension.

The CLI, API, and scheduler emit `workflow.completed` through the existing
event dispatcher after a CLI/API/gallery workflow, scheduled workflow, or
scheduled agent completes. The event carries only the tenant-scoped ticket,
run ID, template/agent ID, and status, uses a deterministic idempotency key,
and records dispatch failures without changing the already-completed workflow
outcome. Pending-approval runs do not emit completion.

Analytics reads the same tenant-scoped execution and approval records. It
reports approval decisions, distinct tickets referenced by normalized sources
or explicit redacted step-input `ticket_id` fields, current `resolved`/`closed`
ticket counts, and grouped workflow/agent/smart-action activity. It does not
infer historical resolution timestamps or measured time saved.

## Template gallery

The local gallery stores provenance-bearing, tenant-scoped instances of the
fixed core workflow catalog. Operators can edit bounded metadata and operator
instructions, enable or disable an instance, inspect redacted revisions, and
restore an earlier definition as a new version. Execution retains the source
template identity and runs through the reviewed core implementation; gallery
metadata cannot introduce arbitrary code, tools, write permissions, or prompts.

## Backfills

Backfills are persisted batches of existing bounded agent runs. The controller
caps a request at 100 ticket IDs, defaults to sequential execution, and allows
up to four bounded workers with deterministic result accounting. It records each
run and failure and supports queued/paused/completed/cancelled state plus
failed-item reruns. The
`POST /agent-backfills/preview` endpoint validates the same agent, ticket, input,
and tenant scope without persisting or executing anything, and reports the
bounded sequential run estimate. Backfills do not bypass the normal agent,
approval, redaction, or tenant checks.

## Technician teammate

`POST /technician/chat` and `wait-local-agent technician-chat` provide a
technician-only conversational command surface over the existing smart-action
service. The parser accepts a small explicit vocabulary for ticket summaries,
triage, similar-ticket search, documentation search, resolution suggestions,
quality, sentiment, escalation, and dispatch suggestions. It never evaluates
arbitrary code or forwards the whole message to a model; unsupported requests
return bounded help text, and existing smart-action approval and tenant checks
remain authoritative.

## End-user support mode

End-user support is disabled by default. When explicitly enabled with
`WAIT_END_USER_SUPPORT_ENABLED=true`, a dedicated bearer token is bound to one
client and one requester via `WAIT_END_USER_CLIENT_ID` and
`WAIT_END_USER_USER_ID`. The `/end-user/tickets` routes can create a local
request, expose only that requester's status, and mark that request escalated.
They cannot choose a tenant, inspect another requester's ticket, invoke smart
actions, or access technician/admin routes. The local ticket boundary is ready
for a governed PSA adapter; live PSA synchronization and outbound delivery are
not implied by enabling it.

## Event-triggered agents

- `POST /automation/events` accepts supported ticket events with an
  `Idempotency-Key` header or request-body key.
- Event definitions use `trigger: "event"` and deterministic filters such as
  `{"event_type": "ticket.created", "priority": "P1"}`.
- CLI/API/gallery workflow and scheduled workflow/agent completion emits `workflow.completed` with
  `workflow_run_id`, `workflow_template_id`, and `status` fields; these can be
  used in deterministic filters to trigger the next bounded agent.
- Deliveries persist redacted payloads, matched definitions, run IDs, status,
  errors, tenant scope, and the next bounded retry time in SQLite. Duplicate
  keys do not execute again. APScheduler runs a single local retry worker every
  30 seconds; it claims at most ten due failures per pass and applies the same
  three-attempt cap used by the technician retry route.

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
