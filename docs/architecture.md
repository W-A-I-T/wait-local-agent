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
- HaloPSA write path modeled as local draft, approval review, and explicit execution;
  the shared smart-action catalog reuses the same governed write boundary
- Hudu read-only documentation context
- IT Glue read-only organization-scoped documentation context
- Confluence Cloud read-only page listing and detail through REST API v2
- Notion mapped-page search, markdown retrieval, data-source schema and bounded
  row queries through the documented API, plus an approval-gated bounded page
  comment write
- SharePoint read-only site and drive-item metadata through Microsoft Graph
- Microsoft Graph read-only user and group context lookup through the guarded
  HTTP boundary
- ConnectWise PSA ticket and company lookup plus an allowlisted,
  approval-gated ticket PATCH path through a guarded, credential-isolated
  adapter.
- Syncro ticket and customer lookup plus documented paginated ticket-comment
  history and the documented ticket-comment endpoint through the same guarded,
  credential-isolated boundary; the comment action remains allowlisted,
  tenant-scoped, and approval-gated, while broader mutation endpoints are
  intentionally absent.
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
  adapters. Successful delivery returns an opaque local receipt ID, UTC
  acceptance timestamp, and bounded adapter status (including the webhook HTTP
  status code when available). Smart-action run output persists that receipt
  through the existing redacted audit boundary; provider response bodies and
  credentials are never returned or persisted.

## Workflow and Scheduler

- Fixed workflow template catalog in the public core, including tool-backed
  ticket-quality, sentiment, escalation, similar-ticket, security-alert,
  L1-resolution, and duplicate-ticket review templates
- Tool-backed templates call the existing smart-action registry through a small
  executor contract, so workflow runs do not create a second tool engine
- Workflow runs persisted with status, message, and approval linkage
- APScheduler-backed scheduled jobs loaded from SQLite at startup
- Scheduled workflow and ticket-agent routes mounted under `/scheduled-jobs`
- UTC cron, interval, and future one-time schedules with pause, resume,
  tenant-scoped reschedule, delete, and audit tracking
- Pause, resume, tenant-scoped reschedule, delete, and audit tracking for
  scheduled jobs
- Agent definitions may gate execution with validated `HH:MM` windows in an
  IANA timezone; overnight windows are supported and closed scheduled jobs are
  audited without creating a run.

## Bounded agents

- Agent definitions persist a short, explicit sequence of existing smart
  actions in SQLite. An explicitly reviewed definition may opt into bounded
  result-aware continuation through the same provider boundary; each next tool
  is validated against the definition, duplicate tools are not re-executed, and
  provider failure falls back to the reviewed sequence.
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
  Agent definitions may add a persisted, revisioned approval rule for selected
  enabled tools. The rule only makes execution stricter: catalog-required
  approvals remain required, and the policy cannot grant access or change a
  tool's role, risk, or write boundary.
- Existing HaloPSA, ConnectWise PSA, Syncro, ServiceNow, and Autotask ticket
  reads, plus Hudu article and IT Glue document reads, are exposed through the
  same tool contract. The actions reuse the guarded connector clients, require
  an explicit local tenant scope, and never accept connector credentials in
  action payloads. Confluence and SharePoint tools return metadata only; they
  do not expose page bodies or file contents. The Notion tool returns only
  mapped page metadata and bounded markdown. A separate data-source metadata
  read returns only bounded property names/types, while the data-source query
  tool uses an explicit local client-to-data-source map and a fixed bounded
  read body. The `notion-page-comment` action previews Markdown locally and
  requires approval and the write opt-in before using the documented comments
  endpoint; other comments and page/property writes remain unavailable.
- The read-first Microsoft 365 identity tool searches tenant-scoped,
  previously collected `m365-user` inventory. The separate connector surface
  can perform bounded live Graph user, group, subscribed-license, mailbox-folder,
  message-metadata, and Intune managed-device reads with operator-supplied
  credentials. The
  `m365-live-context` tool exposes those fixed read resources without accepting
  credentials in its payload, while an
  approval-gated user creation path that resolves a temporary password only
  from the local vault at execution time, plus an approval-gated disable path
  that only sets `accountEnabled=false`. Credentials never enter action or
  approval payloads. Intune managed-device retirement is a separate
  approval-gated, strict-ID action; it does not expose wipe or delete. A
  separate approval-gated managed-device sync action accepts only a strict
  device ID, sends no request body, and does not expose wipe or delete. A
  separate approval-gated managed-device reboot action follows the same
  strict-ID and bodyless-write boundary; wipe and delete remain unavailable. A
  shared smart-action catalog reuses these four managed-device operations with
  the same strict-ID, health, and approval boundaries. A
  separate approval-gated mailbox-settings action accepts only timezone,
  locale, date-format, and time-format fields; message contents and forwarding
  are not exposed. A separate approval-gated message-move action accepts only
  explicit mailbox, source-folder, message, and destination-folder IDs; it
  does not expose message contents or send operations. A separate
  approval-gated message read-state action accepts only explicit mailbox,
  source-folder, and message IDs plus a boolean read state. Group membership changes
  are a distinct strict-ID add/remove action using the same approval path. A
  separate approval-gated message-delete action accepts only explicit mailbox,
  source-folder, and message IDs, sends no body, and does not expose permanent
  deletion. All three bounded message mutations are also available through the
  shared smart-action catalog, which reuses these same validation and approval
  boundaries.
- The RMM boundary normalizes tenant-scoped `endpoint-agent` collector assets
  and exposes a shared contract for device lookup, alerts, script metadata,
  script preview, execution lookup, and approval-aware execution. The local
  adapter has no live alert/script source and blocks execution. The NinjaOne
  adapter uses an explicit WAIT-to-NinjaOne organization map, filters returned
  inventory to that organization, and implements the same contract without
  accepting credentials or provider scope IDs in action payloads. The Datto
  adapter uses an explicit client-to-site map for bounded inventory and jobs.
  The N-able N-central adapter maps WAIT clients to explicit organization-unit
  IDs, filters devices/issues/tasks to those IDs, and supports only the
  documented direct-task POST and status GET for an existing numeric task item
  and in-scope device. Execution requires the existing write flag and approval
  path; execution scope is persisted locally before status lookup.
  The N-able N-sight adapter maps WAIT clients to explicit N-sight client IDs,
  reads documented site/server/workstation XML inventory, derives bounded health
  alerts, and exposes no inferred script or write path.
  The TimeZest adapter maps WAIT clients to one explicit Autotask or ConnectWise
  PSA company ID, uses the documented scheduling-request list filter, rechecks
  returned associated entities, and exposes bounded read status and appointment
  metadata. The documented create endpoint is exposed separately through the
  approval-aware smart-action runtime with an explicit mapped company,
  allow-write flag, and read/write provider key; reschedule and cancel
  mutations are not inferred.
  The ScalePad adapter maps WAIT clients to explicit Core client IDs and a
  separate optional ControlMap tenant-ID map, uses the documented filters,
  rechecks returned provider scope, and exposes bounded redacted client or risk
  summary records. Core IDs and ControlMap tenant IDs are never inferred to be
  interchangeable. Writes and other unscoped reads are not inferred.
  The Kaseya VSA X adapter uses the documented Basic-auth v3 API, an explicit
  client-to-organization map, and read-only device plus device-notification
  paths; script execution and remediation remain unavailable in this adapter.
  The ScreenConnect adapter uses the documented RESTful API Manager extension,
  an explicit client-to-session UUID map, and read-only session detail lookup.
  An optional local command catalog supports approval-gated command submission;
  provider-side alerts, script discovery, and polling are not inferred.
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
  the definition version used. Approval-paused runs can be cancelled through
  the same approval path, and terminal failed/rejected/cancelled runs can be
  retried. Event agents can depend on same-tenant agents; the dispatcher
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
ticket counts, explicit tenant-scoped local/imported ticket status history, and
grouped workflow/agent/smart-action activity. Historical resolution duration is
calculated only from an explicit non-terminal-to-terminal status transition and
a valid creation timestamp; it does not infer provider history or measured time
saved.

## Client reports and automation opportunities

The report service provides deterministic client-scoped QBR and
automation-opportunity builders. They use locally stored ticket records,
explicit ticket status history, smart-action runs, and execution records. A
report can rank repeated successful actions as workflow candidates, but report
generation never enables or executes a workflow. Declared per-action time
savings are surfaced as estimates, not measurements; the builders do not claim
SLA compliance, sentiment, or provider lifecycle evidence that is not present.

The API routes, CLI commands, and `/reports` React controls all reuse this
service. Non-admin report requests are bound to the authenticated client, and
cross-client detail/export requests return not found. Report creation and
export carry the client scope into the audit event.

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
remain authoritative. The `/technician/chat/sessions` routes and the CLI
session options persist bounded, tenant- and principal-scoped conversation
history. History contains only redacted user/assistant operational summaries,
action IDs, statuses, and ticket references; hidden reasoning and provider
payloads are not persisted. Sessions can be closed, after which new messages
are rejected.

The operator dashboard exposes the same session lifecycle at
`/technician-chat`. It creates, selects, sends messages to, and closes sessions
through these routes; it does not introduce a second planner, tool catalog, or
provider path. Viewer tokens receive an access explanation and no chat request
is made.

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

The React client surface is available at `/end-user` when the mode is enabled.
It uses the separate token, supports local request creation, requester-scoped
status lookup, requester/support conversation messages, and technician
escalation, and does not load the operator shell. Technicians and administrators
can review and add local support replies through
`GET/POST /tickets/{ticket_id}/end-user-messages` and the Tickets screen; the
write route requires a technician role and the authenticated tenant scope.
Follow-up messages use a separate `end_user_messages` table, retain the owning
requester ID for isolation, and record whether the author is the requester or
support. Internal `ticket_notes` are never returned by the end-user message
routes.
The authenticated `/end-user/config` route returns optional local branding
configured with `WAIT_END_USER_BRAND_NAME` and `WAIT_END_USER_BRAND_TAGLINE`.
Optional local white-label styling uses validated `WAIT_END_USER_BRAND_LOGO_DATA_URI`,
`WAIT_END_USER_BRAND_ACCENT_COLOR`, and `WAIT_END_USER_BRAND_SURFACE_COLOR` values;
remote image URLs are not loaded.
It returns only validated display values after the same client/requester scope
check; live PSA synchronization and outbound delivery remain separate
capabilities.
End-user ticket responses contain the requester's redacted subject and body,
status, and priority only; client identity is not returned.

## Event-triggered agents

- `POST /automation/events` accepts supported ticket events with an
  `Idempotency-Key` header or request-body key.
- Event definitions use `trigger: "event"` and deterministic filters such as
  `{"event_type": "ticket.created", "priority": "P1"}`.
- CLI/API/gallery workflow and scheduled workflow/agent completion emits `workflow.completed` with
  `workflow_run_id`, `workflow_template_id`, and `status` fields; these can be
  used in deterministic filters to trigger the next bounded agent.
- Deliveries persist redacted payloads, matched definitions, run IDs, status,
  errors, tenant scope, retry policy, and the next bounded retry time in SQLite.
  Duplicate keys do not execute again. APScheduler runs a single local retry
  worker every 30 seconds; it claims at most ten due failures per pass. API
  callers may choose 0-10 retries and a 1-3600 second base delay per delivery;
  defaults remain three attempts and 60 seconds with capped exponential backoff.

## Bounded agents

- Agent definitions persist a short, explicit sequence of existing smart
  actions in SQLite.
- The first public agent mode is manual and ticket-scoped. Definitions allow
  only registered tools, cap runs at eight steps and 120 seconds, and retain
  the configured client scope.
- Each tool call delegates to `SmartActionService`, so existing approval,
  redaction, tenancy, and provider behavior is reused rather than duplicated.
- Agent runs are grouped in the existing execution observability tables with
  one redacted step record per tool. Event triggers, schedules, dependencies,
  backfills, and conversational agents remain future extensions.

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
