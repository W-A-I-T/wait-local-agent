# WAIT Local Agent

WAIT Local Agent is a local-first MSP copilot appliance for tickets, runbooks,
approval-gated workflow drafts, and auditable technician decisions. It is built
for MSPs, IT consultants, and privacy-sensitive SMB teams that want useful
automation without making a SaaS platform the mandatory home for client
knowledge.

The first product wedge is **WAIT Local Agent for MSPs**: private ticket
intelligence with cited local sources, HaloPSA-first connector drafts, local
approval queues, and a clear event history.

## Why This Exists

MSP teams want faster service desk work, but many do not want every runbook,
client note, ticket detail, and technician decision routed through a closed
cloud platform. WAIT Local Agent starts from a different premise:

- Keep client and runbook knowledge local by default.
- Cite the source material behind summaries and drafts.
- Draft connector writes before execution.
- Require technician approval for sensitive actions.
- Keep audit and workflow history in local SQLite.
- Package the runtime as a Docker appliance that an MSP can inspect and support.

## Current Capabilities

- FastAPI operator API and Typer CLI.
- React/Vite dashboard scaffold.
- Docker Compose appliance with API, UI, health check, and SQLite volume.
- Local backup and restore commands.
- SQLite ticket, approval, approval request, workflow run, event, document, and
  chunk storage.
- SQLite FTS5 local knowledge search.
- Markdown, plain text, and text-based PDF ingestion.
- Deterministic ticket classification and summary drafting.
- Optional local OpenAI-compatible model invocation for Ollama, vLLM, or similar
  endpoints.
- Source citations with document paths and excerpts.
- Five initial workflow templates: ticket triage, assign technician, inactive
  ticket follow-up, P1 alert, and documentation-assisted response.
- HaloPSA read-only connector surface for health, tickets, notes, clients,
  assets, and categories when explicitly enabled.
- HaloPSA safe draft surface for add-note, status update, assignment, and
  response draft actions.
- Safe defaults for local-only operation.

## Current Limits

- HaloPSA reads require `WAIT_ALLOW_HTTP_PROBING=true` and credentials.
- HaloPSA write execution is not enabled yet; the current write surface creates
  safe approval drafts.
- RMM, Microsoft 365, Entra, Hudu, IT Glue, and SharePoint live connectors are
  staged roadmap work.
- PDF support is text extraction only. Scanned PDFs and OCR are not supported
  yet.
- Local model invocation is opt-in and calls only the configured local
  OpenAI-compatible endpoint.
- Cloud fallback is disabled by default and not required for the current demo.
- Live write execution remains disabled unless explicitly implemented,
  configured, and approved.

## Requirements

- Python 3.12.
- Node.js 22 for the dashboard.
- Docker and Docker Compose for the appliance path.
- Local filesystem access to the documents you want to ingest.
- Optional: Ollama, vLLM, or another OpenAI-compatible local model endpoint.

## Quick Start

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

wait-local-agent doctor
```

If your Linux Python install does not include `venv`, use `uv`:

```bash
uv run --extra dev wait-local-agent doctor
```

## Run The Local Demo

```bash
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1002
wait-local-agent workflows templates
wait-local-agent workflows run documentation-assisted-response TCK-1002
wait-local-agent approvals list
wait-local-agent events list
```

Or run the scripted demo:

```bash
scripts/demo_appliance.sh
```

Serve the API:

```bash
wait-local-agent serve --host 127.0.0.1 --port 8788
```

Run the dashboard:

```bash
cd ui
npm install
npm run dev
```

## Docker Appliance

```bash
docker compose up --build
```

- API: `http://127.0.0.1:8788`
- Dashboard: `http://127.0.0.1:5173`
- SQLite state: Docker volume `wait-local-agent-data`

Health and product surfaces:

```bash
curl http://127.0.0.1:8788/health
curl http://127.0.0.1:8788/tickets
curl http://127.0.0.1:8788/workflows/templates
curl http://127.0.0.1:8788/connectors
curl http://127.0.0.1:8788/connectors/halopsa/health
curl http://127.0.0.1:8788/connectors/halopsa/tickets
curl http://127.0.0.1:8788/approval-requests
curl http://127.0.0.1:8788/event-history
```

## Backup And Restore

```bash
wait-local-agent backup create .wait-local-agent/backups/state.db
wait-local-agent backup restore .wait-local-agent/backups/state.db

scripts/backup_state.sh
scripts/restore_state.sh .wait-local-agent/backups/state.db
```

## HaloPSA Drafts

Set the connector environment values when you are ready to configure HaloPSA:

```bash
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
```

HaloPSA reads stay blocked until `WAIT_ALLOW_HTTP_PROBING=true`. The current
write surface drafts actions and creates approval requests. It does not execute
live writes yet.

```bash
wait-local-agent connectors list
wait-local-agent connectors secrets
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket TCK-1002
wait-local-agent connectors halopsa-notes TCK-1002
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-assets CLIENT-1
wait-local-agent connectors halopsa-categories
wait-local-agent connectors draft-halopsa TCK-1002 add_note \
  --field note="Drafted response ready for review" \
  --field visibility=internal
wait-local-agent approvals list
```

## Configuration

The runtime starts local and conservative.

```bash
WAIT_DATA_PATH=.wait-local-agent/state.db
WAIT_ALLOWED_DOC_ROOT=examples/sample_docs
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_HTTP_PROBING=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
WAIT_LOCAL_MODEL_PROVIDER=deterministic
WAIT_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
WAIT_LOCAL_MODEL_NAME=llama3.1
WAIT_LOCAL_MODEL_TIMEOUT_SECONDS=20
WAIT_VECTOR_BACKEND=sqlite
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
```

No write actions, external probing, local model inference, cloud fallback, or
live connector execution are enabled by default.

## Local Model Invocation

The default provider is deterministic so tests, demos, and offline installs are
repeatable. To try a local OpenAI-compatible endpoint, run Ollama, vLLM, or
another compatible server on infrastructure you control, then opt in:

```bash
WAIT_ALLOW_LLM_INFERENCE=true
WAIT_LOCAL_MODEL_PROVIDER=ollama
WAIT_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
WAIT_LOCAL_MODEL_NAME=llama3.1
WAIT_LOCAL_MODEL_TIMEOUT_SECONDS=20
```

`WAIT_LOCAL_MODEL_PROVIDER` accepts `deterministic`, `openai-compatible`,
`ollama`, or `vllm`. Timeouts, connection errors, non-success responses, empty
responses, and malformed JSON all fall back to the deterministic provider.

## Development Checks

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

## Product Model

- **WAIT**: parent platform for local vertical copilots.
- **WAIT Local Agent**: local runtime, API, dashboard, and appliance package.
- **WAIT MSP Pack**: first vertical pack for MSP ticket intelligence and
  approval-gated workflows.
- **WAIT Sync**: optional cloud coordination, updates, templates, and fallback
  services.
- **WAIT Adaptation**: paid deployment, customization, workflow design, and
  hardening.

## Roadmap

See [docs/status.md](docs/status.md), [docs/architecture.md](docs/architecture.md),
and [docs/roadmap.md](docs/roadmap.md).
