# WAIT Local Agent

WAIT Local Agent is an open-source, local-first AI copilot runtime for MSPs and SMBs. It runs on customer-controlled infrastructure, connects to operational knowledge and ticket workflows, and keeps human approval and audit logs at the center of every assisted action.

The first product focus is **WAIT Local Agent for MSPs**: ticket intelligence, documentation retrieval, suggested technician responses, and approval-first workflow automation.

## Product Model

- **WAIT**: parent platform for local vertical copilots
- **WAIT Local Agent**: local runtime and API
- **WAIT MSP Pack**: first vertical pack for MSP ticket intelligence
- **WAIT Sync**: optional cloud coordination, updates, templates, and fallback services
- **WAIT Adaptation**: paid deployment, customization, workflow design, and hardening

## Current Capabilities

- FastAPI operator API
- Typer CLI
- SQLite audit and ticket store
- Local model provider abstraction
- Ollama and vLLM configuration placeholders
- Deterministic sample ticket summarization with source citations
- Approval and audit-log workflow
- React/Vite dashboard scaffold
- Public-surface audit script for release hygiene

## Safe Defaults

The runtime starts local and conservative.

```bash
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_HTTP_PROBING=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
WAIT_LOCAL_MODEL_NAME=llama3.1
```

No write actions, external probing, or cloud fallback are enabled unless explicitly configured.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

wait-local-agent doctor
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1001
wait-local-agent audit list
wait-local-agent serve --host 127.0.0.1 --port 8788
```

In another shell:

```bash
cd ui
npm install
npm run dev
```

## API

```bash
curl http://127.0.0.1:8788/health
curl http://127.0.0.1:8788/tickets
curl http://127.0.0.1:8788/tickets/TCK-1001/summary
curl http://127.0.0.1:8788/audit
```

## Development Checks

```bash
python3 -m pytest
python3 scripts/public_surface_audit.py

cd ui
npm install
npm run test
npm run build
```

## Roadmap

See [docs/status.md](docs/status.md) and [docs/roadmap.md](docs/roadmap.md).

