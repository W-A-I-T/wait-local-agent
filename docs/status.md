# Status

WAIT Local Agent is moving from bootstrap demo to local MSP appliance.

## Ready Now

- FastAPI operator API and Typer CLI.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit
  events, event history, documents, and FTS5 chunks.
- Markdown, text, and text-based PDF ingestion.
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

## Next

- Richer workflow filters and run details.
- Hudu documentation connector.
- Connector credential validation and encrypted local secret storage.
- RBAC and audit export.

## Not Ready Yet

- Live RMM, M365, Hudu, IT Glue, or SharePoint synchronization.
- Scanned PDF OCR.
- Multi-tenant hosted control plane.
- Ungated side effects. HaloPSA writes require explicit flags, credentials, and
  approval; other live writes remain disabled.
