# Status

WAIT Local Agent is moving from bootstrap demo to local MSP appliance.

## Ready Now

- FastAPI operator API and Typer CLI.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit
  events, event history, documents, and FTS5 chunks.
- Markdown, text, and text-based PDF ingestion.
- Optional Docling parser/OCR configuration for scanned or richer documents
  when the optional dependency is installed and OCR is explicitly enabled.
- SQLite FTS5 knowledge retrieval by default, with optional Qdrant vector
  backend configuration.
- Deterministic ticket intelligence with indexed citations.
- Optional local OpenAI-compatible provider with deterministic fallback.
- API-backed dashboard for HaloPSA tickets, approval queue, event history,
  knowledge, workflows, connectors, and provider health.
- Docker Compose appliance scaffold with API, UI, health check, and persistent
  SQLite volume.
- Local backup and restore commands.
- HaloPSA read-only connector surface behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA safe write draft surface with approved live execution for ticket
  notes, responses, status/category fields, and technician assignment.
- Hudu read-only connector configuration surface for documentation lookup.
- Approval request payload preview before connector execution, with approve,
  reject, and draft revision paths.
- Release validation script for backend checks, public surface audit, UI tests,
  and UI build.

## Next

- Richer workflow filters and run details.
- Connector credential validation and encrypted local secret storage.
- RBAC and audit export.

## Not Ready Yet

- Live RMM, M365, Hudu, IT Glue, or SharePoint write synchronization.
- Ungated OCR. Scanned PDF OCR requires the optional Docling install and
  explicit OCR opt-in.
- Multi-tenant hosted control plane.
- Ungated side effects. HaloPSA writes require explicit flags, credentials, and
  approval; other live writes remain disabled.

## Commercial Readiness

**Phase 1 (current) — 90% ready for public promotion after safety fixes:**

Critical blockers before promoting the public repo:

- [ ] API authentication — Bearer token middleware on all routes (`security.py`)
- [ ] Encrypted secrets vault — Fernet-encrypted connector credentials (`vault.py`)
- [ ] Redaction expansion — cover `apikey`, `auth_token`, `bearer` key variants

**Phase 2 (needed for MSP commercial launch):**

- [ ] RBAC enforcement (admin / technician / viewer roles with route-level checks)
- [ ] Audit export (`GET /audit-events/export?format=csv|json`)
- [ ] Approver identity in audit events (SHA-256 token pseudonym)
- [ ] Encrypted backup option
- [ ] Connector credential validation CLI command
- [ ] Rate limiting

**Gap vs NeoAgent (primary cloud competitor at $1,000–$2,000/month):**

| Capability | Status |
| --- | --- |
| HaloPSA read + approval-gated write | ✓ Built |
| Hudu read-only | ✓ Built |
| Local/self-hosted | ✓ Built (unique — NeoAgent cloud-only) |
| Open-source inspectable | ✓ Built (unique) |
| Air-gap compatible | ✓ Built (unique) |
| IT Glue connector | Phase 3 (MSP Pack) |
| ConnectWise PSA connector | Phase 4 (MSP Pack) |
| Autotask connector | Phase 4 (MSP Pack) |
| NinjaOne / Datto RMM connectors | Phase 4 (MSP Pack) |
| M365 / Entra read-only | Phase 4 (MSP Pack) |
| Scheduled / proactive workflows | Phase 3 |
| QBR / ROI reporting | Phase 3 (MSP Pack) |
| Startup/founder mode | Phase 4 (Founder Pack) |
| LP evidence bundle export | Phase 5 (Founder Pack) |
| SOC 2 certification | Phase 7+ |

See `docs/competitive-analysis.md` for the full 10-competitor analysis.
See `docs/build-plan.md` for the phased implementation plan.
See `docs/commercial-model.md` for pricing and go-to-market strategy.
