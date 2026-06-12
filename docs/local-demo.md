# Local Demo

This demo keeps WAIT Local Agent on the local deterministic path:

- no live connector writes
- no outbound connector probing
- no cloud fallback
- no model inference
- no real client data

## Scripted path

From a Python environment with the package installed:

```bash
scripts/demo_appliance.sh
```

The script runs:

```bash
wait-local-agent doctor
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1001
wait-local-agent workflows templates
wait-local-agent workflows run ticket-triage TCK-1001
wait-local-agent connectors list
wait-local-agent events list
```

## Docker appliance path

```bash
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
llm_inference_enabled=false
api_auth_required=false
```

## Synthetic launch data

The `demo/` directory contains public-safe launch data that can be used for screenshots and walkthroughs:

```bash
WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent knowledge ingest demo/sample_runbooks

WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent ingest demo/sample_tickets

WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent tickets summarize DEMO-1001
```

## Optional API token demo

Demo mode allows local unauthenticated access only when `WAIT_DEMO_MODE=true` and `WAIT_API_TOKEN` is empty. To test the production gate locally:

```bash
WAIT_DEMO_MODE=false WAIT_API_TOKEN=local-token wait-local-agent serve
curl -H 'Authorization: Bearer local-token' http://127.0.0.1:8788/health
```
