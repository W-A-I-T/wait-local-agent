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
- Approval request payload preview before connector execution, with approve, reject, draft revision, and approver identity capture.
- Scheduled workflow registration, pause, resume, delete, and audit trail.
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
| IT Glue connector | Future paid pack or open-core interface |
| ConnectWise PSA connector | Future paid pack or open-core interface |
| Autotask connector | Future paid pack or open-core interface |
| RMM connectors | Future paid pack or open-core interface |
| M365 / Entra read-only | Future connector phase |
| Scheduled / proactive workflows | Built |
| QBR / ROI reporting | Future paid pack |
| Founder public API/CLI contract | Built in open core; proprietary implementation remains private |
| LP evidence bundle export | Public contract built; proprietary founder implementation remains private |

See `docs/roadmap.md`, `docs/build-plan.md`, `docs/commercial-model.md`, and `docs/open-core-boundary.md` for scope and sequencing.
