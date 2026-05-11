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
