# Status

WAIT Local Agent is moving from bootstrap demo to local MSP appliance.

## Ready Now

- FastAPI operator API and Typer CLI.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit
  events, event history, documents, and FTS5 chunks.
- Markdown, text, and text-based PDF ingestion.
- Deterministic ticket intelligence with indexed citations.
- Optional local OpenAI-compatible provider with deterministic fallback.
- Dashboard scaffold for tickets, approval queue, event history, knowledge,
  workflows, connectors, and provider health.
- Docker Compose appliance scaffold with API, UI, health check, and persistent
  SQLite volume.
- Local backup and restore commands.
- HaloPSA read-only connector surface behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA safe write draft surface that creates approval requests before any
  live connector write exists.

## Next

- Approved HaloPSA write execution after draft review.
- Richer workflow filters and run details.
- Hudu documentation connector.
- Connector credential validation and encrypted local secret storage.
- RBAC and audit export.

## Not Ready Yet

- Live HaloPSA write execution.
- Live RMM, M365, Hudu, IT Glue, or SharePoint synchronization.
- Scanned PDF OCR.
- Multi-tenant hosted control plane.
- Ungated side effects. All live writes remain disabled unless explicitly
  implemented, configured, and approved.
