# Status

WAIT Local Agent is moving from bootstrap demo to local MSP appliance.

## Ready now

- FastAPI operator API and Typer CLI.
- Optional Bearer token API gate outside local demo mode.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit events, event history, documents, and FTS5 chunks.
- Markdown, text, and text-based PDF ingestion.
- Optional Docling parser/OCR configuration for scanned or richer documents when the optional dependency is installed and OCR is explicitly enabled.
- SQLite FTS5 knowledge retrieval by default, with optional Qdrant vector backend configuration.
- Deterministic ticket intelligence with indexed citations.
- Optional local OpenAI-compatible provider with deterministic fallback.
- API-backed dashboard for HaloPSA tickets, approval queue, event history, knowledge, workflows, connectors, and provider health.
- Docker Compose appliance scaffold with API, UI, health check, and persistent SQLite volume.
- Local backup and restore commands.
- JSON and CSV event history export.
- Optional Fernet-backed local secrets vault for connector credentials.
- HaloPSA read-only connector surface behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA safe write draft surface with approved live execution for ticket notes, responses, status/category fields, and technician assignment.
- Hudu read-only connector configuration surface for documentation lookup.
- Approval request payload preview before connector execution, with approve, reject, and draft revision paths.
- Release validation script for backend checks, public surface audit, UI tests, and UI build.
- Launch scaffolding: install helper, issue templates, demo data path, CHANGELOG, and launch docs.

## Next

- RBAC roles and route-level authorization.
- Tenant/client boundaries across stored and connector data.
- Connector setup validation command with scoped credential checks.
- Encrypted backup option.
- Update channel design.

## Not ready yet

- Live RMM, M365, Hudu, IT Glue, or SharePoint write synchronization.
- Ungated OCR. Scanned PDF OCR requires the optional Docling install and explicit OCR opt-in.
- Multi-tenant hosted control plane.
- Ungated side effects. HaloPSA writes require explicit flags, credentials, and approval; other live writes remain disabled.
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

**Phase 5+ commercial hardening still required:**

- [ ] RBAC enforcement with admin, technician, and viewer roles.
- [ ] Approver identity in audit events.
- [ ] Tenant/client boundary enforcement on all queries and connector views.
- [ ] Encrypted backup option.
- [ ] Connector credential validation CLI command.
- [ ] Rate limiting.
- [ ] Signed update channel.

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
| Scheduled / proactive workflows | Future phase |
| QBR / ROI reporting | Future paid pack |
| Founder mode implementation | Future paid pack |
| LP evidence bundle export | Future paid pack |

See `docs/roadmap.md`, `docs/build-plan.md`, `docs/commercial-model.md`, and `docs/open-core-boundary.md` for scope and sequencing.
