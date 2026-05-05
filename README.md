# WAIT Local Agent

WAIT Local Agent is a local-first AI copilot runtime for MSPs, IT consultants, and privacy-sensitive SMB teams. It is designed to run on infrastructure the operator controls, index local operational knowledge, summarize service work with citations, and keep every action behind human approval and audit logs.

The first product path is **WAIT Local Agent for MSPs**: a private ticket-intelligence layer that helps technicians find the right runbook, classify requests, draft client-safe responses, and preserve a clear local record of what happened.

## Why This Exists

Many service teams want AI assistance without making a mandatory SaaS agent the center of their operational knowledge. WAIT Local Agent starts from a different premise:

- Keep client and runbook knowledge local by default.
- Cite the source material behind every summary or draft.
- Require human approval before workflow execution.
- Keep audit logs in a local SQLite store.
- Let MSPs and consultants customize, inspect, and eventually resell vertical packs.

## Who It Is For

- MSPs that want a private technician-assist layer for tickets and runbooks.
- IT consultants who deploy repeatable local copilots for multiple clients.
- SMB operators with sensitive internal procedures, client files, or compliance pressure.
- Builders who want an open local runtime for vertical copilots instead of a closed SaaS-only workflow.

## Current Capabilities

- FastAPI operator API
- Typer CLI
- SQLite ticket, approval, audit, document, and chunk storage
- SQLite FTS5 local knowledge search
- Markdown, plain text, and text-based PDF ingestion
- Ticket classification and deterministic summary drafting
- Optional local OpenAI-compatible model invocation for Ollama, vLLM, or similar endpoints
- Source citations with document paths and excerpts
- React/Vite dashboard scaffold with ticket, audit, provider, and knowledge views
- Safe defaults for local-only operation

## Current Limits

- PDF support is text extraction only. Scanned PDFs and OCR are not supported yet.
- PSA, RMM, Microsoft 365, Entra, Hudu, IT Glue, and SharePoint connectors are not live yet.
- Local model invocation is opt-in and calls only the configured local OpenAI-compatible endpoint.
- Cloud fallback is disabled by default and not required for the current demo.
- Approval-gated execution exists as a product direction; the current runtime focuses on ticket intelligence and knowledge retrieval.

## Requirements

- Python 3.12
- Node.js 22 for the dashboard
- Local filesystem access to the documents you want to ingest
- Optional: Ollama, vLLM, or another OpenAI-compatible local model endpoint

## Quick Start

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

wait-local-agent doctor
```

If your Linux Python install does not include `venv`, you can use `uv` instead:

```bash
uv run --extra dev wait-local-agent doctor
```

## Replicate the Local Demo

Ingest the sample knowledge base and sample tickets:

```bash
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
```

Search local knowledge:

```bash
wait-local-agent knowledge list
wait-local-agent knowledge search "mailbox permissions"
```

Summarize a ticket with cited sources:

```bash
wait-local-agent tickets summarize TCK-1002
wait-local-agent audit list
```

Serve the API:

```bash
wait-local-agent serve --host 127.0.0.1 --port 8788
```

Use the API:

```bash
curl http://127.0.0.1:8788/health
curl http://127.0.0.1:8788/tickets
curl http://127.0.0.1:8788/tickets/TCK-1002/summary
curl http://127.0.0.1:8788/knowledge/documents
curl "http://127.0.0.1:8788/knowledge/search?q=mailbox%20permissions"
curl http://127.0.0.1:8788/audit
```

Run the dashboard:

```bash
cd ui
npm install
npm run dev
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
```

No write actions, external probing, local model inference, or cloud fallback are enabled unless explicitly configured.

### Local Model Invocation

The default provider is deterministic so tests, demos, and offline installs are repeatable. To try a local OpenAI-compatible endpoint, run Ollama, vLLM, or another compatible server on infrastructure you control, then opt in:

```bash
WAIT_ALLOW_LLM_INFERENCE=true
WAIT_LOCAL_MODEL_PROVIDER=ollama
WAIT_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
WAIT_LOCAL_MODEL_NAME=llama3.1
WAIT_LOCAL_MODEL_TIMEOUT_SECONDS=20
```

`WAIT_LOCAL_MODEL_PROVIDER` accepts `deterministic`, `openai-compatible`, `ollama`, or `vllm`. The runtime posts to `{WAIT_LOCAL_MODEL_BASE_URL}/chat/completions` and expects JSON with `summary` and `suggested_response`. If inference is disabled, the endpoint is unavailable, the request times out, the response is non-successful, or the model returns malformed JSON, WAIT Local Agent falls back to the deterministic provider and keeps the ticket summary response stable.

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

## Issues and Feature Requests

Use GitHub issues for:

- Bugs with clear reproduction steps
- Documentation gaps
- Connector requests for PSA, RMM, documentation, identity, email, or chat systems
- Workflow/playbook ideas for MSP or SMB operations
- Security hardening suggestions

A useful issue usually includes:

- What you tried to do
- The command or API request you ran
- Expected behavior
- Actual behavior
- Relevant logs or traceback
- Operating system and Python/Node versions
- Whether the issue uses sample data or your own local documents

Do not include client secrets, private customer data, API keys, or production runbooks in public issues.

## Product Model

- **WAIT**: parent platform for local vertical copilots
- **WAIT Local Agent**: local runtime and API
- **WAIT MSP Pack**: first vertical pack for MSP ticket intelligence
- **WAIT Sync**: optional cloud coordination, updates, templates, and fallback services
- **WAIT Adaptation**: paid deployment, customization, workflow design, and hardening

## Roadmap

See [docs/status.md](docs/status.md) and [docs/roadmap.md](docs/roadmap.md).
