# Local Demo

This walkthrough stays on the deterministic local path:

- no live connector writes
- no outbound connector probing
- no cloud fallback
- no local model inference
- no real client data

## Scripted path

From a Python environment with the package installed:

```bash
scripts/demo_appliance.sh
```

The script runs the shipped commands:

The ingest command always supplies an explicit client. For a local demo, the
CLI creates that named demo client if it does not exist; application code must
still pass an existing active client to the store API.

```bash
wait-local-agent doctor
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets --client-id acme
wait-local-agent tickets summarize TCK-1001
wait-local-agent workflows templates
wait-local-agent workflows run ticket-triage TCK-1001
wait-local-agent connectors list
wait-local-agent events list
```

## Docker appliance path

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- API: `http://127.0.0.1:8788`
- Dashboard: `http://127.0.0.1:5173`

Health check:

```bash
curl http://127.0.0.1:8788/health
```

Expected demo defaults:

```text
write_actions_enabled=false
http_probing_enabled=false
cloud_fallback_enabled=false
offline_mode=false
llm_inference_enabled=false
api_auth_required=false
demo_mode=true
```

The demo is bounded to a demo client. Provider writes and deployments are
disabled, and `/secrets` returns HTTP 403.

## Demo auth model

Demo mode is an explicit opt-in and is open only when the appliance stays in its
local demo configuration:

```text
WAIT_DEMO_MODE=true
WAIT_API_TOKEN=
WAIT_ADMIN_TOKEN=
WAIT_TECH_TOKEN=
WAIT_VIEWER_TOKEN=
```

If you set role tokens for a shared test, also set `WAIT_DEMO_MODE=false` and
configure `WAIT_ADMIN_TOKEN`, `WAIT_API_TOKEN`, or an active persisted
`msp_admin` principal credential before startup.

## Synthetic launch data

The `demo/` directory contains public-safe runbooks and tickets for screenshots and walkthroughs:

```bash
WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent knowledge ingest demo/sample_runbooks

WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent ingest demo/sample_tickets --client-id acme

WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent tickets summarize DEMO-1001
```

## Optional API token demo

Demo mode allows local unauthenticated access only when `WAIT_DEMO_MODE=true`.
To test the non-demo startup and request gate locally:

```bash
WAIT_DEMO_MODE=false WAIT_ADMIN_TOKEN=local-admin-token wait-local-agent serve
curl -H 'Authorization: Bearer local-admin-token' http://127.0.0.1:8788/health
```

## Consultant mode demo

The Microsoft consultant-mode surfaces also have a deterministic local
walkthrough:

```bash
scripts/demo_consultant_mode.sh
```

See [the consultant demo](../consultant/consultant-demo.md) for the scope and synthetic
inputs. It does not contact Microsoft services or deploy a solution.
