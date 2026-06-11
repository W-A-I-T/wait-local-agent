# WAIT Local Agent

**Local-first AI copilot for MSPs and founders. Tickets, runbooks, approvals, and knowledge — on your hardware, with your rules.**

WAIT Local Agent is an open-source, self-hosted AI automation appliance for MSPs and startup teams. It provides ticket intelligence, runbook search, PSA workflow drafts, and a technician approval queue — without sending client data or project files to a third-party cloud.

Apache 2.0 · Self-hosted Docker · No mandatory cloud account · HaloPSA + Hudu built-in

---

> ⚠️ **Safety guarantee**: Live PSA writes require explicit operator opt-in (`WAIT_ALLOW_WRITE_ACTIONS=true`) and human approval in the approval queue. They are disabled in every fresh install and in the demo path.

---

## Why Local-First

Every major MSP AI automation tool — NeoAgent ($1,000–$2,000/month), Atera Robin, SuperOps Monica, ConnectWise zofiQ — runs on a third-party cloud and requires routing client tickets, runbooks, and technician decisions through a vendor's infrastructure.

WAIT Local Agent is the only open-source, self-hosted alternative:

- **Privacy by design** — client data stays on your hardware by default
- **Inspectable** — read every line; no black box
- **Air-gap compatible** — runs fully offline with no cloud dependencies
- **10–20× cheaper** — free open core; $99/month MSP Pack vs $1,000+/month cloud tools
- **MSPs and founders** — two modes, two personas, one appliance

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

**Also a WAIT Launch Passport companion**: If you use [WAIT Launch Passport](https://app.waittech.io) for technical launch audits, the Founder Pack lets you run a private preflight check locally and export a signed evidence bundle directly to your LP scan — without uploading source code.

## Current Capabilities

- FastAPI operator API and Typer CLI.
- React/Vite dashboard for HaloPSA tickets, approvals, connector health, and
  execution history.
- Docker Compose appliance with API, UI, health check, and SQLite volume.
- Local backup and restore commands.
- SQLite ticket, approval, approval request, workflow run, event, document, and
  chunk storage.
- SQLite FTS5 local knowledge search.
- Markdown, plain text, text-based PDF ingestion, and optional Docling-backed
  document parsing/OCR when explicitly installed and enabled.
- SQLite retrieval by default, with optional Qdrant vector storage for local or
  configured Qdrant deployments.
- Deterministic ticket classification and summary drafting.
- Optional local OpenAI-compatible model invocation for Ollama, vLLM, or similar
  endpoints.
- Source citations with document paths and excerpts.
- Five initial workflow templates: ticket triage, assign technician, inactive
  ticket follow-up, P1 alert, and documentation-assisted response.
- HaloPSA read-only connector surface for health, tickets, notes, clients,
  assets, and categories when explicitly enabled.
- HaloPSA safe draft and approved live-write surface for add-note,
  client-safe response, status/category updates, ticket fields, and technician
  assignment.
- Hudu read-only connector surface for health, companies, articles, article
  detail, and folders when explicitly enabled.
- Approval requests expose the proposed connector payload before execution so a
  technician can review, edit through the draft flow, approve, or reject.
- Safe defaults for local-only operation.

## Current Limits

- HaloPSA reads require `WAIT_ALLOW_HTTP_PROBING=true` and credentials.
- HaloPSA live writes require `WAIT_ALLOW_HTTP_PROBING=true`,
  `WAIT_ALLOW_WRITE_ACTIONS=true`, credentials, and an approved draft.
- RMM, Microsoft 365, Entra, IT Glue, and SharePoint live connectors are staged
  roadmap work.
- OCR is optional and disabled by default. Install the Docling extra and set the
  parser/OCR flags before using it for scanned PDFs.
- Qdrant is optional. SQLite FTS5 remains the default retrieval backend.
- Local model invocation is opt-in and calls only the configured local
  OpenAI-compatible endpoint.
- Cloud fallback is disabled by default and not required for the current demo.
- Live write execution remains disabled unless explicitly configured and
  approved.

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
curl http://127.0.0.1:8788/connectors/halopsa/write-health
curl http://127.0.0.1:8788/connectors/halopsa/tickets
curl http://127.0.0.1:8788/connectors/hudu/health
curl http://127.0.0.1:8788/connectors/hudu/companies
curl http://127.0.0.1:8788/connectors/hudu/articles
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

## HaloPSA Live Writes

Set the connector environment values when you are ready to configure HaloPSA:

```bash
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
WAIT_HALOPSA_TICKET_WRITE_ENDPOINT=Ticket
WAIT_HALOPSA_ACTION_WRITE_ENDPOINT=Actions
```

HaloPSA reads stay blocked until `WAIT_ALLOW_HTTP_PROBING=true`. Live writes
also require `WAIT_ALLOW_WRITE_ACTIONS=true` and an approved draft. Approving a
HaloPSA approval request auto-executes the write when both flags are enabled;
approved requests can also be retried manually.

```bash
wait-local-agent connectors list
wait-local-agent connectors secrets
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-write-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket TCK-1002
wait-local-agent connectors halopsa-notes TCK-1002
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-assets CLIENT-1
wait-local-agent connectors halopsa-categories
wait-local-agent connectors draft-halopsa HALO-1002 add_note \
  --field note="Internal note ready for review"
wait-local-agent connectors draft-halopsa HALO-1002 draft_response \
  --field response="Client-safe response ready to post"
wait-local-agent connectors draft-halopsa HALO-1002 update_status \
  --field status_id=9
wait-local-agent connectors draft-halopsa HALO-1002 assign_technician \
  --field technician_id=42
wait-local-agent connectors draft-halopsa HALO-1002 update_ticket_fields \
  --field category_id=5 \
  --field priority=High
wait-local-agent approvals list
wait-local-agent approvals show 1
wait-local-agent approvals edit-field 1 note="Reviewed by technician"
wait-local-agent approvals update 1 approved "approved by technician"
wait-local-agent connectors execute-halopsa 1
```

Remote HaloPSA payloads and secrets are not stored in local state. WAIT records
only sanitized execution metadata: request id, action type, status, endpoint,
HTTP status code, remote id when available, and a concise result message.

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

## Knowledge Extras

The default knowledge path uses built-in Markdown/text/PDF extraction and
SQLite FTS5. Optional document and vector capabilities are installed only when
needed:

```bash
pip install -e ".[docling]"    # Docling parser/OCR support
pip install -e ".[qdrant]"     # Qdrant vector backend support
pip install -e ".[knowledge]"  # Both optional knowledge extras
```

Docling OCR remains opt-in at runtime:

```bash
WAIT_DOCUMENT_PARSER=docling
WAIT_ALLOW_OCR=true
```

Qdrant remains opt-in at runtime:

```bash
WAIT_VECTOR_BACKEND=qdrant
WAIT_EMBEDDING_PROVIDER=fastembed
WAIT_QDRANT_PATH=.wait-local-agent/qdrant
# or point at an existing service:
WAIT_QDRANT_URL=http://127.0.0.1:6333
```

If these extras are not installed or enabled, the appliance stays on the
deterministic local SQLite path.

## Hudu Read-Only Connector

Hudu is treated as documentation context, not a live write surface. Configure it
only when you want read-only documentation lookup through the connector layer:

```bash
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
WAIT_HUDU_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

```bash
wait-local-agent connectors hudu-health
wait-local-agent connectors hudu-companies
wait-local-agent connectors hudu-articles --company-id CLIENT-1
wait-local-agent connectors hudu-article ARTICLE-1
wait-local-agent connectors hudu-folders --company-id CLIENT-1
```

Hudu writes are not part of the public surface.

## Development Checks

```bash
scripts/validate_release.sh
```

The release validation script runs the backend quality gates, public surface
audit, UI tests, and UI production build. The individual commands are:

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

## Product Tiers

| Tier | Price | What's included |
| --- | --- | --- |
| **Open Core** | Free (Apache 2.0) | Full runtime, HaloPSA + Hudu, 5 templates, approval queue, knowledge base, Docker Compose |
| **WAIT MSP Pack** | $99/month | + IT Glue, ConnectWise, Autotask, NinjaOne, M365/Entra, scheduled workflows, QBR reports, ROI dashboard |
| **WAIT Founder Pack** | $49/month | + Project scanner, evidence vault, LP preflight, LP bundle export, developer handoff |
| **WAIT Sync** | $29/month | + Template marketplace, encrypted cloud backup, team coordination |
| **WAIT Agent Appliance** | $499/month | + All packs, RBAC setup, Vault, TLS, air-gap, SLA support |

See [docs/commercial-model.md](docs/commercial-model.md) for full pricing and open-core licensing details.

## Competitor Comparison

| | WAIT Local Agent | NeoAgent | Atera+Robin | SuperOps+Monica |
|---|---|---|---|---|
| **Price** | Free + $99/mo | $1,000–$2,000/mo | $129–$209/tech/mo | $89–$179/tech/mo |
| **Self-hosted** | ✓ | ✗ | ✗ | ✗ |
| **Open source** | ✓ (Apache 2.0) | ✗ | ✗ | ✗ |
| **Air-gap** | ✓ | ✗ | ✗ | ✗ |
| **PSA-agnostic** | ✓ | ✓ | ✗ (Atera-only) | ✗ (SuperOps-only) |
| **Founder mode** | ✓ (Founder Pack) | ✗ | ✗ | ✗ |

See [docs/competitive-analysis.md](docs/competitive-analysis.md) for the full 10-competitor analysis.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  WAIT Local Agent — Local-First AI Copilot Appliance     │
│                                                         │
│  ┌───────────────┐  ┌────────────────┐  ┌───────────┐  │
│  │ WAIT MSP Pack │  │Founder Pack    │  │WAIT Sync  │  │
│  │ $99/mo (paid) │  │$49/mo (paid)   │  │$29/mo     │  │
│  └──────┬────────┘  └───────┬────────┘  └─────┬─────┘  │
│         │                   │                  │        │
│  ┌──────┴───────────────────┴──────────────────┴─────┐  │
│  │    PUBLIC OPEN-SOURCE CORE (Apache 2.0, Free)      │  │
│  │  FastAPI · Typer CLI · SQLite FTS5                 │  │
│  │  HaloPSA · Hudu · Approval Engine · Dashboard      │  │
│  └───────────────────────┬────────────────────────────┘  │
│                           │ optional, user-triggered      │
│  ┌────────────────────────▼───────────────────────────┐  │
│  │  WAIT Ecosystem (all opt-in)                        │  │
│  │  Launch Passport · Investor Diligence Passport      │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Documentation

| Doc | Contents |
| --- | --- |
| [docs/product-architecture.md](docs/product-architecture.md) | Full product architecture, layers, MSP + founder mode design, security model |
| [docs/build-plan.md](docs/build-plan.md) | Phases 0–8 with task-level detail |
| [docs/competitive-analysis.md](docs/competitive-analysis.md) | 10-competitor comparison including NeoAgent, Atera, SuperOps, ConnectWise |
| [docs/commercial-model.md](docs/commercial-model.md) | Pricing, open-core strategy, go-to-market |
| [docs/ecosystem-integration.md](docs/ecosystem-integration.md) | LP/IDP/AER data contracts and CollectorBundle format |
| [docs/security-model.md](docs/security-model.md) | Threat model, safe-by-default policy, RBAC |
| [docs/architecture.md](docs/architecture.md) | Technical component architecture |
| [docs/roadmap.md](docs/roadmap.md) | Phase-by-phase feature roadmap |
| [docs/status.md](docs/status.md) | Current implementation status and commercial readiness |

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) and [docs/status.md](docs/status.md).
