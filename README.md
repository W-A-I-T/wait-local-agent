# WAIT Local Agent

**Local-first MSP automation appliance for tickets, runbooks, approvals, connector drafts, and audit history.**

WAIT Local Agent is an Apache 2.0, self-hosted copilot runtime for MSPs and founder-led teams that want inspectable local automation instead of a cloud-first control plane. It keeps the core appliance local: FastAPI, Typer CLI, React dashboard, SQLite state, local knowledge search, approval queue, and HaloPSA/Hudu connector surfaces.

> **Safety guarantee:** live PSA writes require explicit operator opt-in (`WAIT_ALLOW_WRITE_ACTIONS=true`) and a human-approved approval request. They are disabled in every fresh install and in the demo path.

## What works now

- Docker Compose appliance with API, dashboard, health check, and persistent SQLite volume.
- FastAPI operator API and Typer CLI.
- Optional Bearer token API gate outside local demo mode.
- SQLite-backed tickets, approvals, approval requests, workflow runs, audit events, event history, documents, and FTS5 chunks.
- Markdown, plain text, and text-based PDF ingestion.
- SQLite FTS5 knowledge retrieval by default.
- Optional Docling/OCR and Qdrant extras when explicitly installed and enabled.
- Deterministic ticket classification and summary drafting with citations.
- Optional local OpenAI-compatible model provider; disabled by default.
- JSON and CSV event history export.
- Optional Fernet-backed local secrets vault for connector credentials.
- HaloPSA read paths for health, tickets, notes, clients, assets, and categories behind `WAIT_ALLOW_HTTP_PROBING=true`.
- HaloPSA write drafts and approved live execution for notes, responses, status/category fields, ticket fields, and technician assignment.
- Hudu read-only documentation context for health, companies, articles, article detail, and folders.
- Approval queue with payload preview, edit-before-approval, approve, reject, execute, and event history views.
- Launch scaffolding: install helper, synthetic demo data, CHANGELOG, docs, and GitHub issue templates.

## Not ready yet

- Ungated live writes.
- Hosted multi-tenant control plane.
- Live RMM, Microsoft 365, Entra, IT Glue, SharePoint, or Hudu write synchronization.
- RBAC roles, tenant/client boundaries, encrypted backup, signed update channel, and rate limiting.
- Proprietary MSP Pack or Founder Pack implementation in this public repository.

See `docs/status.md` and `docs/roadmap.md` for phase-by-phase status.

## Open-core boundary

This repository contains the free open core: runtime, CLI, store, approval engine, connector framework, HaloPSA + Hudu open-core surfaces, workflow schema, dashboard, tests, docs, and appliance packaging.

Paid or proprietary pack implementation must not be committed here. Private pack work belongs in `W-A-I-T/wait-local-agent-packs` or another private repository. The local `packs/` directory is gitignored for proprietary pack installs.

See `docs/open-core-boundary.md` and `docs/commercial-model.md`.

## Requirements

- Python 3.12 for local CLI/API development.
- Docker with Compose support for the appliance path.
- Node.js 22 for dashboard development outside Docker.
- Optional local model endpoint such as Ollama or vLLM.

## Quick start: local CLI

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
wait-local-agent doctor
```

Run the deterministic demo:

```bash
scripts/demo_appliance.sh
```

Manual demo steps:

```bash
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1002
wait-local-agent workflows templates
wait-local-agent workflows run documentation-assisted-response TCK-1002
wait-local-agent approvals list
wait-local-agent events list
```

## Quick start: Docker appliance

```bash
docker compose up --build
```

- API: `http://127.0.0.1:8788`
- Dashboard: `http://127.0.0.1:5173`
- SQLite state: Docker volume `wait-local-agent-data`

Health check:

```bash
curl http://127.0.0.1:8788/health
```

Expected demo defaults:

```text
write_actions_enabled=false
http_probing_enabled=false
cloud_fallback_enabled=false
llm_inference_enabled=false
api_auth_required=false
```

One-command helper:

```bash
scripts/install.sh
```

## Configuration defaults

`.env.example`, Dockerfile, and Compose defaults keep the appliance local and conservative.

```bash
WAIT_DATA_PATH=.wait-local-agent/state.db
WAIT_ALLOWED_DOC_ROOT=examples/sample_docs
WAIT_API_TOKEN=
WAIT_DEMO_MODE=true
WAIT_SECRETS_BACKEND=env
WAIT_VAULT_PATH=.wait-local-agent/vault
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_HTTP_PROBING=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
WAIT_LOCAL_MODEL_PROVIDER=deterministic
WAIT_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
WAIT_LOCAL_MODEL_NAME=llama3.1
WAIT_LOCAL_MODEL_TIMEOUT_SECONDS=20
WAIT_VECTOR_BACKEND=sqlite
WAIT_DOCUMENT_PARSER=basic
WAIT_ALLOW_OCR=false
WAIT_EMBEDDING_PROVIDER=none
WAIT_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
WAIT_QDRANT_PATH=.wait-local-agent/qdrant
WAIT_QDRANT_URL=
WAIT_QDRANT_COLLECTION=wait_knowledge_chunks
WAIT_CONNECTOR_TIMEOUT_SECONDS=20
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
WAIT_HALOPSA_TICKET_WRITE_ENDPOINT=Ticket
WAIT_HALOPSA_ACTION_WRITE_ENDPOINT=Actions
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
WAIT_HUDU_PAGE_SIZE=25
```

## API authentication

Local demo mode allows unauthenticated local API access only when both conditions are true:

```text
WAIT_DEMO_MODE=true
WAIT_API_TOKEN=
```

For any shared host or production-style install:

```bash
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=<strong-local-token>
wait-local-agent serve
curl -H 'Authorization: Bearer <strong-local-token>' http://127.0.0.1:8788/health
```

## Secrets vault

Environment variables remain the default for local demos. For longer-lived connector credentials:

```bash
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=.wait-local-agent/vault
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
wait-local-agent secrets list
```

`secrets list` prints key names only. Treat `secrets get` output as sensitive terminal output.

## HaloPSA connector

Reads require credentials and `WAIT_ALLOW_HTTP_PROBING=true`:

```bash
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket HALO-1002
wait-local-agent connectors halopsa-notes HALO-1002
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-categories
```

Writes require credentials, `WAIT_ALLOW_HTTP_PROBING=true`, `WAIT_ALLOW_WRITE_ACTIONS=true`, a draft, and human approval:

```bash
wait-local-agent connectors draft-halopsa HALO-1002 add_note \
  --field note="Internal note ready for review"
wait-local-agent approvals show 1
wait-local-agent approvals edit-field 1 note="Reviewed by technician"
wait-local-agent approvals update 1 approved "approved by technician"
wait-local-agent connectors execute-halopsa 1
```

Execution records sanitized metadata only: request id, action type, status, endpoint, HTTP status code, remote id when available, and concise result message.

## Hudu connector

Hudu is read-only documentation context in this public repo.

```bash
wait-local-agent connectors hudu-health
wait-local-agent connectors hudu-companies
wait-local-agent connectors hudu-articles
wait-local-agent connectors hudu-article ARTICLE-1
wait-local-agent connectors hudu-folders
```

## Backup, restore, and audit export

```bash
wait-local-agent backup create .wait-local-agent/backups/state.db
wait-local-agent backup restore .wait-local-agent/backups/state.db
scripts/backup_state.sh
scripts/restore_state.sh .wait-local-agent/backups/state.db
```

```bash
wait-local-agent audit export .wait-local-agent/audit.json
wait-local-agent audit export .wait-local-agent/audit.csv --format csv
curl http://127.0.0.1:8788/audit/export
curl 'http://127.0.0.1:8788/audit/export?export_format=csv'
```

## Local model and knowledge extras

The default provider is deterministic so tests, demos, and offline installs are repeatable. To try a local model endpoint:

```bash
WAIT_ALLOW_LLM_INFERENCE=true
WAIT_LOCAL_MODEL_PROVIDER=ollama
WAIT_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
WAIT_LOCAL_MODEL_NAME=llama3.1
```

Optional knowledge extras:

```bash
pip install -e ".[docling]"    # Docling parser/OCR support
pip install -e ".[qdrant]"     # Qdrant vector backend support
pip install -e ".[knowledge]"  # Both optional knowledge extras
```

Docling OCR remains disabled until `WAIT_DOCUMENT_PARSER=docling` and `WAIT_ALLOW_OCR=true` are set. Qdrant remains disabled until `WAIT_VECTOR_BACKEND=qdrant` is set.

## Development checks

```bash
scripts/validate_release.sh
```

Manual equivalents:

```bash
ruff check .
mypy src tests
bandit -r src
pip-audit --skip-editable
python -m pytest --cov=wait_local_agent --cov-report=term-missing --cov-fail-under=95
python scripts/public_surface_audit.py

cd ui
npm install
npm run test
npm run build
```

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│ WAIT Local Agent                                             │
│                                                              │
│ Dashboard ── FastAPI ── SQLite store                         │
│     │          │          │                                  │
│     │          │          ├─ tickets / approvals / events     │
│     │          │          └─ knowledge docs / FTS chunks      │
│     │          │                                             │
│     │          ├─ deterministic or explicit local provider    │
│     │          ├─ HaloPSA read + approval-gated write         │
│     │          └─ Hudu read-only context                      │
│     │                                                        │
│ Typer CLI ── backup / restore / audit export / vault          │
└──────────────────────────────────────────────────────────────┘
```

## Documentation

| Doc | Contents |
| --- | --- |
| [docs/local-demo.md](docs/local-demo.md) | Local demo and synthetic launch data |
| [docs/appliance-install.md](docs/appliance-install.md) | Docker Compose appliance install path |
| [docs/security-model.md](docs/security-model.md) | Safe defaults, auth, vault, audit, approval gates |
| [docs/connector-setup.md](docs/connector-setup.md) | HaloPSA and Hudu setup |
| [docs/open-core-boundary.md](docs/open-core-boundary.md) | Public vs proprietary pack boundary |
| [docs/launch-checklist.md](docs/launch-checklist.md) | Release and launch readiness checklist |
| [docs/roadmap.md](docs/roadmap.md) | Phase-by-phase roadmap |
| [docs/commercial-model.md](docs/commercial-model.md) | Open-core and commercial model |
| [docs/status.md](docs/status.md) | Current implementation status |
| [docs/architecture.md](docs/architecture.md) | Technical component architecture |

## License

Apache 2.0. See [LICENSE](LICENSE).
