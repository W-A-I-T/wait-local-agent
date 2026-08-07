# Status

WAIT Local Agent is moving from bootstrap demo to local MSP appliance.

## Ready now

- FastAPI operator API and Typer CLI.
- Optional bearer token API gate outside local demo mode, with admin, technician, and viewer roles.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit events, event history, documents, and FTS5 chunks.
- Approval requests persist a 24-hour default expiry; expired requests are
  audited and cannot be approved, edited, or executed.
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
- Connector setup validation commands for HaloPSA, Hudu, NinjaOne, and Autotask.
- HaloPSA read-only connector surface behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA safe write draft surface with approved live execution for ticket notes, responses, status/category fields, and technician assignment.
- Hudu read-only connector configuration surface for documentation lookup.
- IT Glue read-only organization, document, and folder lookup; no IT Glue write
  operations are enabled.
- NinjaOne read-only RMM adapter for device inventory, active alerts, automation
  script metadata, and safe script execution previews. Script execution and all
  NinjaOne management mutations remain disabled.
- Autotask PSA read-only ticket and company inventory; mutation endpoints remain
  disabled.
- Preview-only communication drafts support ticket notes, email, Teams, Slack,
  and SMS-shaped messages; outbound delivery adapters are not enabled.
- Deterministic ticket sentiment reports explainable terms and an escalation
  signal without requiring a model provider.
- The `m365-identity-context` agent tool can read only completed, tenant-scoped
  Microsoft 365 collector runs; Graph mutation paths remain disabled.
- Governed read-only AWS, Azure, GCP, and Microsoft 365 collector modules with
  CLI/API validation, preview, persisted runs, redacted evidence, and export.
- Approval request payload preview before connector execution, with approve, reject, draft revision, and approver identity capture.
- Scheduled workflow and ticket-agent registration, pause, resume, delete,
  reschedule, and audit trail. Cron, interval, and one-time triggers use the
  existing APScheduler path with validated IANA timezones (UTC by default) and
  persist their agent/entity target.
- Bounded agent definitions with an explicit existing-tool allowlist, ticket
  scope, persisted runs, approval pause/resume, and grouped execution traces.
  Scheduled and event agents may enforce a persisted `HH:MM` execution window
  in a validated IANA timezone; manual runs remain available for recovery.
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
  reruns under `/agent-backfills`.
- Analytics now includes a redacted, tenant-scoped activity breakdown by run
  kind, trigger source, and outcome alongside the existing time-series and
  estimated-time-saved metrics, plus requested/decided approval counts and an
  explainable approval rate.
- A `/tools` API catalog that exposes existing smart-action schemas, including
  read-only local knowledge search and ticket-quality checks, risk, required
  role, approval requirement, and read/write classification.
- Signed update-channel client checks with pinned public keys.
- Open-core pack loader plus `wait-local-agent packs` install, list, and status commands.
- Founder API and CLI public contract with stable "pack not installed" behavior when proprietary founder code is absent.
- Route-level rate limiting on public API surfaces.
- Release validation script for backend checks, public surface audit, UI tests, and UI build.
- Launch scaffolding: install helper, issue templates, demo data path, CHANGELOG, and launch docs.

## Next

- Proprietary MSP Pack and Founder Pack implementation in the private pack repo.
- Additional connector families beyond HaloPSA and Hudu.
- Hosted WAIT Sync coordination surfaces and encrypted cloud backup relay.
- White-label and enterprise packaging work.

## Not ready yet

- Live RMM, M365, Hudu, IT Glue, or SharePoint write synchronization.
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
| IT Glue connector | Built in open core as a read-only adapter; writes and richer mapping remain future work |
| ConnectWise PSA connector | Future paid pack or open-core interface |
| Autotask connector | Built in open core as a read-only adapter; mutation and richer mapping remain future work |
| NinjaOne RMM read-only | Built in open core; execution and additional RMM vendors remain future work |
| M365 / Entra read-only inventory | Built through governed collector modules |
| Scheduled / proactive workflows | Built |
| QBR / ROI reporting | Future paid pack |
| Founder public API/CLI contract | Built in open core; proprietary implementation remains private |
| LP evidence bundle export | Public contract built; proprietary founder implementation remains private |

See `docs/roadmap.md`, `docs/build-plan.md`, `docs/commercial-model.md`, and `docs/open-core-boundary.md` for scope and sequencing.
