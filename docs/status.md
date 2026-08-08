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
- Optional local OpenAI-compatible provider with deterministic fallback.
- API-backed dashboard for HaloPSA tickets, approval queue, event history, knowledge, workflows, connectors, and provider health.
- Docker Compose appliance scaffold with API, UI, health check, and persistent SQLite volume.
- Local backup and restore commands, including optional encrypted backups with the Fernet vault.
- JSON and CSV event history export.
- Optional Fernet-backed local secrets vault for connector credentials.
- Connector setup validation commands for HaloPSA and Hudu.
- HaloPSA read-only connector surface behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA safe write draft surface with approved live execution for ticket notes, responses, status/category fields, and technician assignment.
- Hudu read-only connector configuration surface for documentation lookup.
- IT Glue read-only organization-scoped documentation lookup through the common
  guarded HTTP boundary; write operations remain unavailable.
- ConnectWise PSA read-only ticket and company inventory through the common
  guarded HTTP boundary; write operations remain unavailable.
- Syncro read-only ticket and customer inventory through the common guarded
  HTTP boundary; write operations remain unavailable.
- ServiceNow read-only incident and company inventory through the common
  guarded HTTP boundary; write operations remain unavailable.
- Autotask read-only ticket and company inventory through the common guarded
  HTTP boundary; write operations remain unavailable.
- Confluence Cloud read-only page listing and detail through the common guarded
  HTTP boundary; write operations remain unavailable.
- SharePoint read-only site and document metadata through Microsoft Graph; file
  downloads and write operations remain unavailable.
- Microsoft Graph read-only user and group context lookup with externally
  supplied delegated or application bearer credentials; mutations and broader
  resource reads remain unavailable.
- Preview-first communication drafts for email, Teams, Slack, and SMS through
  the common smart-action contract; drafts are approval-gated and explicitly
  non-sendable.
- Approval request payload preview before connector execution, with approve, reject, draft revision, and approver identity capture.
- Scheduled workflow and ticket-agent registration, pause, resume, delete,
  tenant-scoped reschedule, and audit trail. Cron, interval, and one-time
  triggers use the existing UTC APScheduler path and persist their
  agent/entity target; all schedule mutations enforce the authenticated tenant
  boundary.
- Bounded agent definitions with an explicit existing-tool allowlist, ticket
  scope, persisted runs, approval pause/resume, grouped execution traces, and
  technician cancellation for active runs. A pending smart-action approval is
  revoked when its agent run is cancelled. Failed and cancelled runs expose a
  bounded retry route with persisted retry lineage.
  Event-triggered agents now accept authenticated ticket events with
  deterministic filters, idempotency keys, run-once-per-entity protection,
  redacted delivery records, and delivery history APIs. Conversational and
  unrestricted agent execution are not shipped. Immutable revision history,
  explainable redacted diffs, and restore-as-new-version are available under
  `/agents/{id}/revisions`; each new run records the definition version it
  used and exposes its redacted snapshot in run detail. Approval-paused runs
  support cancellation, while terminal failed/rejected/cancelled runs support
  bounded retry; event
  agents also support same-tenant dependency chains with cycle prevention. A
  provenance-bearing tenant-scoped template gallery can run reviewed core
  workflows through the existing approval path. Persisted sequential agent
  backfills now expose progress counts, pause/cancel state, and failed-item
  reruns under `/agent-backfills`. Agent run responses and persisted run state
  include a redacted operational final result with the last tool's status,
  output, evidence, and error detail; hidden reasoning is not persisted.
- Analytics now includes a redacted, tenant-scoped activity breakdown by run
  kind, trigger source, and outcome alongside the existing time-series and
  estimated-time-saved metrics.
- A `/tools` API catalog that exposes existing smart-action schemas, including
  read-only local knowledge search, ticket-quality, sentiment and escalation checks, and collector previews with risk, required role, approval requirement,
  and read/write classification. The catalog also exposes a technician-gated,
  read-only Microsoft 365 identity lookup over tenant-scoped collected
  `m365-user` inventory; no credentials or write operation are accepted by the
  action. A matching read-only RMM device lookup normalizes collected
  `endpoint-agent` assets through the local adapter boundary; remote control
  and vendor credentials are not accepted. Existing HaloPSA ticket reads and
  Hudu article search are available as tenant-scoped read tools using the
  guarded connector clients; connector credentials are never action payloads.
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

- Live RMM, Hudu, IT Glue, Confluence, or SharePoint write synchronization;
  Microsoft Graph broader-resource reads and all M365 writes remain unavailable.
- Ungated OCR. Scanned PDF OCR requires the optional Docling install and explicit OCR opt-in.
- Multi-tenant hosted control plane.
- Ungated side effects. HaloPSA writes require explicit flags, credentials, rate-limit budget, and approval; other live writes remain disabled.
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

**Remaining commercial hardening after the public 1.0.0 repo release:**

- [ ] Full per-connector tenant isolation for every future connector family.
- [ ] Hosted WAIT Sync relay and encrypted off-device backup.
- [ ] White-label branding and enterprise deployment presets.
- [ ] Paid pack distribution, licensing operations, and support workflows.

**Gap vs cloud-first MSP automation competitors:**

| Capability | Status |
| --- | --- |
| HaloPSA read + approval-gated write | Built |
| Hudu read-only | Built |
| Local/self-hosted | Built |
| Open-source inspectable | Built |
| Air-gap compatible default path | Built |
| IT Glue connector | Read-only core surface built |
| ConnectWise PSA connector | Read-only core surface built |
| Autotask connector | Read-only core surface built |
| ServiceNow connector | Read-only core surface built |
| Confluence connector | Read-only core surface built |
| SharePoint connector | Read-only metadata surface built |
| RMM connectors | Local read-only adapter built; vendor adapters future |
| M365 / Entra read-only | Collected-inventory identity lookup plus bounded live Graph user/group/subscribed-license/mailbox-folder lookup built; broader resources future |
| Scheduled / proactive workflows | Built |
| QBR / ROI reporting | Future paid pack |
| Founder public API/CLI contract | Built in open core; proprietary implementation remains private |
| LP evidence bundle export | Public contract built; proprietary founder implementation remains private |

See `docs/roadmap.md`, `docs/build-plan.md`, `docs/commercial-model.md`, and `docs/open-core-boundary.md` for scope and sequencing.
