# Status

WAIT Local Agent is moving from bootstrap demo to local MSP appliance.

## Ready now

- FastAPI operator API and Typer CLI.
- Optional bearer token API gate outside local demo mode, with admin, technician, and viewer roles.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit events, event history, documents, and FTS5 chunks.
- Tenant and client scoping on stored workflow, approval, scheduled job, and audit records.
- Markdown, text, and text-based PDF ingestion.
- Optional Docling parser/OCR configuration for scanned or richer documents when the optional dependency is installed and OCR is explicitly enabled.
- SQLite FTS5 knowledge retrieval by default, with optional Qdrant vector backend configuration.
- Deterministic ticket intelligence with indexed citations.
- Ticket summary and resolution smart actions run through the same deterministic
  local provider when no model is configured; their output is labeled as
  deterministic rather than AI-assisted. Configured local or remote model
  providers remain optional enhancements.
- Optional local OpenAI-compatible provider with deterministic fallback, plus
  explicit remote fallback adapters for Anthropic Messages and documented
  OpenAI-compatible DeepSeek, Kimi, or documented coding-model-compatible endpoints. Remote
  calls remain disabled unless cloud fallback and a complete remote provider
  configuration are enabled; `WAIT_OFFLINE_MODE=true` denies them even when
  that configuration is present.
- Admin-triggered model provider health checks use the configured provider's
  documented model-list contract, report missing models and malformed or
  unavailable responses explicitly, and never probe remote providers while
  offline or when remote fallback is disabled.
- Model completion, planning, and continuation requests retry only transient
  rate-limit, timeout, server, or transport failures within a fixed two-retry
  budget; non-retryable failures stop immediately, and redacted provider
  metadata records the retry count.
- Preview-only bounded planning through `POST /agents/plan` and the React
  Agents screen selects existing approved tools from a natural-language
  instruction using the configured model provider when available and bounded
  deterministic rules otherwise, loads tenant-scoped ticket/client/knowledge
  context, and exposes selection mode, risk, and approval metadata without
  executing the plan; malformed or unavailable model output falls back to
  deterministic rules, and a reviewed result can be converted into a disabled
  draft definition.
- Reviewed agent definitions may opt into bounded result-aware continuation.
  After each successful step, the executor supplies only the redacted operational
  result and remaining catalog to the configured provider, validates one returned
  tool against the definition, and falls back to the reviewed sequence when the
  provider is unavailable or malformed. The default remains the fixed reviewed
  sequence.
- API-backed dashboard for HaloPSA tickets, approval queue, event history, knowledge, workflows, connectors, and provider health.
- Docker Compose appliance scaffold with API, UI, health check, and persistent SQLite volume.
- Local backup and restore commands, including optional encrypted backups with the Fernet vault.
- JSON and CSV event history export.
- Optional Fernet-backed local secrets vault for connector credentials.
- Connector setup validation commands for HaloPSA and Hudu.
- HaloPSA read-only connector surface behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA safe write draft surface with approved live execution for ticket notes, responses, status/category fields, and technician assignment.
- The shared smart-action catalog reuses those governed HaloPSA writes through
  tenant-scoped ticket note, response, status, assignment, and field-update
  actions with action-specific validation.
- The shared catalog also exposes governed ConnectWise PSA status, assignment,
  and ticket-field writes with the same tenant and approval boundaries.
- Hudu read-only connector configuration surface for tenant-scoped documentation
  lookup, bounded article content extraction, and content search.
- IT Glue read-only organization-scoped documentation lookup through the common
  guarded HTTP boundary, including bounded document-name/text/step-content
  search across up to 50 listed candidates and document-detail section
  retrieval; write operations remain unavailable.
- Confluence read-only space-scoped page body retrieval and content search
  through the common guarded HTTP boundary; write operations remain unavailable.
- Notion mapped-page title search, bounded page-markdown retrieval, mapped
  data-source schema retrieval, and mapped data-source row queries through the
  common guarded HTTP boundary; page comments are a separate approval-gated,
  write-opt-in action and broader writes remain unavailable.
- SharePoint read-only site and drive-item metadata plus tenant-scoped Graph
  drive search across a site or folder hierarchy, and explicitly requested
  text-document content retrieval bounded to 20,000 characters; binary/office
  extraction remains unavailable.
- ConnectWise PSA ticket and company inventory plus approval-gated, allowlisted
  ticket status, assignment, and field updates through the common guarded HTTP
  boundary.
- Syncro ticket and customer inventory plus documented paginated ticket-comment
  history and the approval-gated documented ticket-comment action through the
  common guarded HTTP boundary; broader writes remain unavailable.
- ServiceNow incident and company inventory through the common guarded HTTP
  boundary, plus approval-gated work-note and state updates through the shared
  smart-action runtime; broader incident fields remain unavailable.
- Autotask ticket and company inventory through the common guarded HTTP boundary,
  plus approval-gated ticket-note, time-entry, status, resolution, and assignment actions. The note contract requires
  the operator to provide the provider's instance-specific non-negative
  `noteType` and `publish` values, status updates require an explicit provider
  status ID, resolution text is bounded to the documented field, assignment
  requires an explicit positive `assignedResourceID`, and time entries require
  explicit resource/role/date/hours/summary values with hours bounded to the
  provider's documented 0-24-hour range;
  broader write operations remain unavailable.
- NinjaOne RMM device and alert inventory, script catalog and preview, plus
  approval-gated script execution through the bounded tenant-mapped adapter;
  responses and execution lookups remain scope-checked and sanitized.
- Datto RMM device and open-alert inventory plus component metadata through the
  same bounded contract, with explicit client-to-site mapping, approval-gated
  quick-job execution, and bounded job-status lookup.
- N-able N-central device, active-issue, and scheduled-task metadata through the
  same bounded contract with explicit client-to-organization-unit mapping, plus
  approval-gated direct-task submission and locally scoped execution-status
  lookup. Script upload, arbitrary task identifiers, and provider credentials in
  action payloads remain unavailable.
- N-able N-sight tenant-scoped site, server, and workstation inventory,
  documented per-device check, performance-history, asset-details, and monitoring-details inventory, failing-check alerts, mapped-device outages, managed-antivirus
  threats, Backup & Recovery session and 60-day backup-check history through the
  XML Data Extraction API and an explicit client map. Patch approval is available only through the
  approval-gated smart action with the global write flag and mapped-device
  recheck; script catalog, preview, execution, and polling remain explicitly
  unavailable.
- TimeZest tenant-mapped scheduling-request reads and an approval-gated
  documented create action through the documented API, with fixed company
  scoping, bounded status/appointment metadata, local associated-company
  rechecking, explicit HTTP/write flags, and read/write-key enforcement.
  Rescheduling and cancellation remain unavailable because no documented
  mutation contract is claimed.
- ScalePad tenant-mapped Core client inventory, separately mapped ControlMap
  risk-summary reads, and separately mapped Lifecycle Manager goal and
  assessment reads through
  the documented APIs, with exact provider filters, returned-scope rechecking,
  bounded redacted records, and explicit regional base-URL configuration.
  ScalePad writes and other product APIs remain unavailable.
- Kaseya VSA X device and device-notification inventory, script catalog/detail,
  approval-gated execution, and locally scoped execution polling through the
  same bounded contract with explicit client-to-organization mapping. Broader
  remediation, webhook callbacks, and script-source execution remain
  unavailable.
- ScreenConnect session/device reads through the documented RESTful API Manager
  extension with an explicit local client-to-session UUID map, plus approval-gated
  session notes (`AddNoteToSession`), session messages (`SendMessageToSession`),
  and an optional local command catalog with approval-gated
  `SendCommandToSession` submission. Provider-native alert lookup, script
  discovery, and command polling remain unavailable; local commands report
  provider acceptance rather than completion.
- Confluence Cloud read-only page listing and detail through the common guarded
  HTTP boundary; write operations remain unavailable.
- Notion mapped-page title search, page-markdown retrieval, data-source schema
  retrieval, and mapped data-source row queries through the common guarded HTTP
  boundary; page comments use a separate approval-gated, write-opt-in action
  and broader writes remain unavailable.
- SharePoint read-only site and document metadata through Microsoft Graph, plus
  bounded site/folder search and supported text-file retrieval; write
  operations and binary/office extraction remain unavailable.
- Microsoft Graph bounded user, group, tenant-license, per-user license-detail, mailbox-folder, message-metadata, and Intune
  context lookup with externally supplied delegated or application bearer
  credentials, plus admin-approved user creation, disable/offboarding, password
  reset, and explicit authentication-method removal, and
  strict-ID group membership add/remove, direct user license add/remove, and
  approved session revocation, Intune managed-device sync/reboot/retirement/
  remote-lock, and
  allowlisted mailbox-settings updates;
  broader resource reads and other mutations remain unavailable.
- Preview-first communication for local ticket notes, email, Teams, Slack, and
  SMS through the common smart-action contract. Approved local notes are
  tenant-scoped; external delivery supports configured SMTP/webhook adapters
  only when both write and outbound-call flags are enabled. Successful sends
  return and persist an opaque local receipt ID, UTC acceptance time, and
  bounded adapter status; webhook status codes are retained without provider
  response bodies. Receipts are available through smart-action run API/CLI
  views; there is no dedicated communication-history screen.
- Approval request payload preview before connector execution, with approve, reject, draft revision, approver identity capture, and a bounded 24-hour expiry that terminates linked pending work and blocks late execution.
- Agent definitions can shorten approval deadlines with a bounded policy and can
  require additional approval for selected enabled tools. They can also add a
  bounded conditional rule for an explicit ticket priority, status, and/or
  authenticated requester role. Matches are exact and case-insensitive, all
  entered fields are ANDed, and the rule can only add approval. Scheduled and
  event runs have no authenticated requester role and therefore do not match a
  role condition. They cannot extend a tool's configured deadline, remove a
  catalog approval requirement, or grant write access.
- Scheduled workflow and ticket-agent registration, pause, resume, delete, and
  audit trail. Cron, interval, and one-time triggers use the existing
  APScheduler path and persist their agent/entity target plus a validated IANA
  schedule timezone (UTC remains the migration default). Scheduled jobs can
  also be rescheduled through a tenant-scoped API route; pause, resume,
  reschedule, and delete all enforce the authenticated tenant boundary.
  Agent definitions may additionally declare a validated local execution
  window with an IANA timezone, including overnight ranges; closed scheduled
  windows are skipped without creating a run and are recorded in the audit
  trail. Bounded client-scoped QBR, automation-opportunity, and
  recurring-service-review report targets
  reuse the same scheduler and deterministic local report builders with
  validated periods and failure auditing.
- Bounded agent definitions with an explicit existing-tool allowlist, ticket
  scope, persisted runs, approval pause/resume, grouped execution traces, and
  technician cancellation for active runs. A pending smart-action approval is
  revoked when its agent run is cancelled. Failed and cancelled runs expose a
  bounded retry route with persisted retry lineage.
  Event-triggered agents now accept authenticated ticket events with
  deterministic filters, idempotency keys, run-once-per-entity protection,
  redacted delivery records, delivery history APIs, and an operator-triggered
  bounded retry route that retries only failed or dependency-blocked agents
  using persisted per-agent attempt state. Failed deliveries receive a
  persisted UTC due time and are retried automatically by one bounded local
  scheduler worker with exponential backoff capped at one hour; each delivery
  may select a bounded 0-10 retry count and 1-3600 second base delay through
  the event-ingestion API, with three attempts and 60 seconds as defaults. The
  operator route and worker share the persisted policy. Conversational and
  unrestricted agent execution are not shipped. Immutable revision history,
  explainable redacted diffs, and restore-as-new-version are available under
  `/agents/{id}/revisions`; each new run records the definition version it
  used and exposes its redacted snapshot in run detail. Approval-paused runs
  support cancellation, while terminal failed/rejected/cancelled runs support
  bounded retry; event
  agents also support same-tenant dependency chains with cycle prevention. A
  CLI/API/gallery workflow or scheduled workflow/agent completion emits a
  deterministic, tenant-scoped `workflow.completed` event that can trigger
  matching event agents with idempotency and audit history; pending-approval
  runs do not emit completion. A
  React agent builder now creates bounded definitions from the existing tool
  catalog and lets operators select ticket, client, and local-knowledge
  context sources; selected context is recorded with each run. The Agents
  screen also edits existing definitions into new versions, loads revision
  history, compares a prior revision with the current one, and restores a
  prior revision as a new version through the existing tenant-scoped API.
  provenance-bearing tenant-scoped template gallery can create, edit,
  enable/disable, version, compare redacted revision diffs, restore, export
  versioned JSON artifacts, and import validated artifacts as disabled local
  copies before running reviewed core workflows through the existing approval
  path. Gallery runs retain the local template version used for execution.
  Workflow runs can be
  compared through tenant-scoped redacted API, CLI, and React dashboard paths;
  comparisons are limited to operational fields and do not mutate runs.
  Persisted sequential agent
  backfills now expose progress counts, pause/cancel state, and failed-item
  reruns under `/agent-backfills`, plus a non-persisting dry-run estimate and
  bounded parallel execution with a sequential default. The React dashboard
  exposes the same preview, queue, progress, control, and failed-item rerun
  paths without creating a second execution engine.
  Agent run responses and persisted run state
  include a redacted operational final result with the last tool's status,
  output, evidence, and error detail; hidden reasoning is not persisted.
- Technician-only bounded chat commands reuse the smart-action catalog. Explicit
  `plan ... TCK-*` requests also reuse the reviewed `/agents/plan` planner and
  return a preview only; they never execute steps or create an enabled agent.
  Persisted
  tenant- and principal-scoped chat sessions support bounded follow-up context,
  redacted operational history, API routes, CLI session options, and a dedicated
  React `/technician-chat` screen for creating, selecting, messaging, and closing
  sessions. Explicit
  script/device requests can prepare an RMM preview or approval-gated execution
  through the existing RMM action; unrestricted planning, external Teams
  conversation delivery, and an end-user conversational agent are not shipped.
- Optional end-user support can create and track requester-scoped local tickets,
  send isolated requester follow-up messages, and request technician escalation
  through both `/end-user/tickets*` and the separate `/end-user` React surface;
  it does not load the operator shell. The separately scoped
  `/end-user/config` route supports local tenant branding name/tagline, a
  validated local image data URI, and validated accent/surface colors; remote
  image URLs are rejected. Operators can manually prepare an approval-gated
  HaloPSA note draft for a local end-user message after an explicit
  client-to-client mapping and remote ticket ownership check; automatic PSA
  sync and outbound delivery remain unavailable.
- The inactive-ticket follow-up workflow now reuses the shared communication
  action: it prepares a tenant-scoped local ticket-note draft by default, or an
  explicitly selected configured channel, and cannot write or deliver until a
  technician approval completes. A missing or unavailable delivery adapter is
  reported as a failure rather than treated as success.
- The P1 alert workflow uses the same approval-gated communication boundary,
  defaulting to a local ticket note and requiring an explicitly configured
  adapter for external notification channels.
- The documentation-assisted response workflow now executes through the shared
  smart-action catalog: it retrieves tenant-scoped local knowledge, drafts a
  cited response with the deterministic local provider by default (or an
  explicitly enabled provider), shows the draft before approval, and delivers
  only after technician approval. Missing evidence, unavailable providers, and
  unavailable delivery adapters remain explicit failures; no approval is
  created for an ungrounded response.
- Client-scoped QBR, automation-opportunity, and recurring-service-review
  reports are available through their matching `/reports/*` API routes, CLI
  commands, and the `/reports` dashboard. They use local ticket,
  status-history, smart-action, and execution evidence; repeated actions and
  follow-up candidates are review outputs only, and time-saved values are
  explicitly labeled estimates. Report reads, generation, audit, and export
  enforce the authenticated client scope.
- Analytics now includes a redacted, tenant-scoped activity breakdown by run
  kind, trigger source, and outcome alongside the existing time-series and
  estimated-time-saved metrics. It also reports approval decisions, distinct
  execution-referenced tickets, current `resolved`/`closed` ticket counts,
  explicit local/imported ticket status transitions, recorded historical
  resolution counts, and grouped activity by workflow, agent, or smart action.
  Historical resolution duration is calculated only from an explicit recorded
  non-terminal-to-terminal transition and a valid ticket creation timestamp;
  existing snapshots do not receive inferred history. The
  `/tickets/{ticket_id}/status-history` API exposes the tenant-scoped records,
  and the React dashboard exposes the historical metrics at `/analytics` with
  server-side date-range and client filters within the permitted tenant scope.
- The React dashboard exposes `/executions` history with run-kind/status
  filters, redacted step detail, generated artifact metadata, and technician
  artifact downloads through the existing tenant-scoped observability API.
  Smart-action records include
  configured provider/model labels and provider-reported token usage as redacted
  operational metadata when the provider supplies it. When both operator-supplied
  cost rates are configured, `/analytics` aggregates a clearly labeled cost
  estimate; missing pricing or usage remains explicitly unpriced. Credentials
  and hidden reasoning are not persisted.
- The public workflow catalog now includes ten executable review templates
  for ticket quality, sentiment, escalation, technician dispatch,
  similar-ticket, security-alert, L1-resolution, duplicate-ticket, explicit-
  threshold SLA-risk, and stale-ticket analysis. They reuse the existing
  smart-action registry and persist both the
  workflow run and the tenant-scoped smart-action execution; no write action is
  implied by these review templates.
- The smart-action catalog also includes local-only, read-only
  `ticket-sla-assessment` and `stale-ticket-sweep` tools. Operators must provide
  positive thresholds; WAIT does not infer a vendor SLA contract. Ticket age is
  calculated only from an explicit ticket timestamp. Records without one return
  insufficient evidence or are counted as excluded rather than being treated as
  stale.
- A `/tools` API catalog that exposes existing smart-action schemas, including
  read-only local knowledge search, ticket-quality, explicit-threshold SLA-risk
  and stale-ticket checks, sentiment, escalation, and security-alert checks, and collector previews with risk, required role, approval requirement,
  and read/write classification. The catalog also exposes a technician-gated,
  read-only Microsoft 365 identity lookup over tenant-scoped collected
  `m365-user` inventory plus the fixed-resource `m365-live-context` Graph read
  tool, including tenant and per-user license context, plus the admin-only
  approval-gated `m365-user-onboarding`, `m365-user-offboarding`,
  `m365-password-reset`, `m365-authentication-method-remove`, and
  `m365-group-membership` tools. Group membership accepts only immutable
  directory object IDs and an explicit add/remove operation; it remains
  approval-gated and records provider failures without reporting success.
  The catalog also exposes admin-only `m365-license-change` for immutable user
  IDs and one to fifty SKU GUIDs with an explicit add/remove operation; it is
  approval-gated and reports provider failures without fake success.
  It also exposes admin-only `m365-session-revocation` for one immutable user
  ID; active sessions are revoked only after approval and provider failures
  remain explicit failures.
  It also exposes admin-only `m365-password-reset` using a local-vault temporary
  credential reference and `m365-authentication-method-remove` for one explicitly
  identified FIDO2, Microsoft Authenticator, phone, or software OATH method.
  Both are approval-gated; the password is never persisted or returned, and MFA
  removal has no reset-all mode.
  The catalog also exposes admin-only `m365-mailbox-settings` with only the
  existing allowlisted mailbox fields; updates remain approval-gated and
  provider failures are explicit.
  It also exposes admin-only `m365-mail-message-move` for one explicit user,
  source folder, message, and destination folder ID; message moves remain
  previewed and approval-gated, with provider failures reported explicitly.
  The catalog also exposes admin-only `m365-mail-message-read-state` with a
  boolean read state and `m365-mail-message-delete` for one explicit message;
  both remain previewed and approval-gated with explicit provider failures.
  It also exposes admin-only managed-device sync, reboot, retirement, and
  remote-lock actions with one explicit device ID, preview, approval, and
  provider-health gating.
  Onboarding accepts only a validated local-vault reference for the temporary
  credential and reads the secret after approval; offboarding accepts only an
  explicit user identity and directory ID, disables the account, then revokes
  sessions after approval, and reports partial completion without continuing
  after a failed step. Credentials are never accepted in tool payloads.
  A
  matching RMM contract exposes tenant-scoped device and alert
  lookup, script metadata, script preview, and approval-aware execution. The
  local adapter remains inventory-only and blocks execution until a reviewed
  vendor adapter is installed. Existing HaloPSA ticket reads and
  Hudu article-content, IT Glue document-content, Confluence page-content,
  Notion mapped-page markdown, data-source schema, and data-source rows, and SharePoint
  documentation search, and
  ConnectWise PSA, Syncro, ServiceNow, and Autotask ticket lookup are available as
  tenant-scoped read tools using the guarded connector clients. ServiceNow work-note
  and state updates, and Autotask ticket notes/status/resolution updates, are exposed as approval-gated tools;
  connector credentials are never action payloads.
- Signed update-channel client checks with pinned public keys.
- Open-core pack loader plus `wait-local-agent packs` install, list, and status commands.
- Founder API and CLI public contract with stable "pack not installed" behavior when proprietary founder code is absent.
- Route-level rate limiting on public API surfaces.
- Release validation script for backend checks, public surface audit, UI tests, and UI build.
- Launch scaffolding: install helper, issue templates, demo data path, CHANGELOG, and launch docs.

## Next

- Proprietary MSP Pack and Founder Pack implementation in the private pack repo.
- Broader live Microsoft Graph resources and additional RMM/documentation
  capabilities beyond the bounded read surfaces already shipped.
- Hosted WAIT Sync coordination surfaces and encrypted cloud backup relay.
- White-label and enterprise packaging work.

## Not ready yet

- Live RMM, Hudu, IT Glue, Confluence, broader Notion page/property
  synchronization, or SharePoint write synchronization;
  Microsoft Graph broader-resource reads and M365 writes other than approved
  user creation, disable/offboarding, password reset, explicit
  authentication-method removal, group membership, direct license changes,
  session revocation, Intune managed-device sync/reboot/retirement, mailbox-settings,
  message-move, message-read-state, and message-delete updates remain
  unavailable.
- Ungated OCR. Scanned PDF OCR requires the optional Docling install and explicit OCR opt-in.
- Multi-tenant hosted control plane.
- Ungated side effects. PSA writes require explicit flags, credentials, rate-limit budget, and approval; Syncro is limited to its documented comment action and other live writes remain disabled.
- Paid MSP Pack or Founder Pack implementation in this public repo.

## Commercial readiness

**Phase 1 — public-core launch readiness improved:**

| Item | Status |
| --- | --- |
| API authentication | Implemented outside demo mode |
| Encrypted local secrets vault | Implemented as optional Fernet backend |
| Redaction expansion | Implemented for common token and authorization variants |
| Audit export | Implemented for event history JSON and CSV |
| Open-core boundary | Documented; `packs/` ignored |
| Launch assets | Added baseline docs, issue templates, install helper, demo data, and CHANGELOG |

**Remaining commercial hardening after the public 1.1.1 repo release:**

- [ ] Full per-connector tenant isolation for every future connector family.
- [ ] Hosted WAIT Sync relay and encrypted off-device backup.
- [ ] White-label branding and enterprise deployment presets.
- [ ] Paid pack distribution, licensing operations, and support workflows.

**Gap vs cloud-first MSP automation competitors:**

| Capability | Status |
| --- | --- |
| HaloPSA read + approval-gated write | Built |
| Hudu read-only | Built, including bounded article content search |
| IT Glue read-only | Built, including bounded organization document-content search and document-detail section retrieval |
| Confluence read-only | Built, including bounded page content search |
| Notion bounded surface | Built, including mapped-page title search, bounded page-markdown retrieval, mapped data-source schema/row reads, and approval-gated page comments; broader writes remain future |
| Local/self-hosted | Built |
| Open-source inspectable | Built |
| Air-gap compatible default path | Built |
| IT Glue connector | Read-only core surface plus bounded content search built |
| ConnectWise PSA connector | Bounded read surface plus approval-gated status, assignment, and allowlisted ticket-field writes built |
| Syncro connector | Bounded ticket/customer reads, documented paginated ticket-comment history, and approval-gated documented ticket comments built; broader writes remain future |
| Autotask connector | Ticket/company reads plus approval-gated ticket-note, time-entry, status, resolution, and assignment updates built; broader writes remain future |
| ServiceNow connector | Incident/company reads plus approval-gated work-note, state, assignment, and resolution-metadata updates built; resolution metadata and state remain separate actions; broader writes remain future |
| TimeZest connector | Tenant-mapped scheduling-request inventory plus approval-gated documented creation built; rescheduling, cancellation, and broader marketplace actions remain future |
| ScalePad connector | Tenant-mapped, read-only Core client, separately mapped ControlMap risk-summary, and separately mapped Lifecycle Manager goal/assessment reads built; documented filters and cursor pagination are bounded and surfaced through API, CLI, and Agents tooling; writes, unscoped reads, and other ScalePad product APIs remain future |
| Confluence connector | Read-only core surface built |
| Notion connector | Mapped-page search, bounded markdown/schema/row reads, and approval-gated page comments built; broader writes remain future |
| SharePoint connector | Read-only metadata and bounded site/folder content-search surface plus bounded text-document retrieval built |
| RMM connectors | Local, NinjaOne, Datto, bounded N-central inventory/direct-task, N-sight device/check/performance-history/asset-details/monitoring-details, documented failing-check, managed-antivirus threat, mapped-device outage, Backup & Recovery session, and 60-day backup-check history reads, mapped-device patch inventory, and approval-gated patch approval/reprocessing plus allowlisted patch policy operations, Kaseya VSA X inventory/notification plus approval-gated script catalog/detail/execution/polling, and ScreenConnect session/device, approval-gated session note/message, plus optional local-command adapters built; broader vendor coverage, N-sight script/antivirus writes/scans, backup mutations, provider-native ScreenConnect discovery/polling, and broader remediation remain future |
| M365 / Entra | Collected-inventory identity lookup plus bounded live Graph user/group/subscribed-license/per-user-license-detail/mailbox-folder/message-metadata/Intune managed-device lookup and approved user creation/disable-offboarding/password-reset/authentication-method-removal/group membership/direct-license/session-revocation/managed-device-sync/reboot/retirement/remote-lock/mailbox-settings/message-move/read-state/delete changes built; shared smart-action coverage includes the governed M365 mutation catalog and approval-gated onboarding/offboarding/password-reset/authentication-method-removal/license-request workflow templates; broader resources and mutations future |
| Scheduled / proactive workflows | Built; workflow, agent, and bounded QBR, automation-opportunity, and recurring-service-review client-report targets are available |
| QBR / ROI reporting | Deterministic client-scoped QBR, automation-opportunity, and recurring-service-review reports built with JSON, Markdown, and PDF export; provider-backed lifecycle enrichment remains future work |
| Founder public API/CLI contract | Built in open core; proprietary implementation remains private |
| LP evidence bundle export | Public contract built; proprietary founder implementation remains private |

See `docs/roadmap.md`, `docs/build-plan.md`, `docs/commercial-model.md`, and `docs/open-core-boundary.md` for scope and sequencing.
