# Configuration

WAIT Local Agent reads environment variables into the `Settings` dataclass in
`src/wait_local_agent/config.py`. The high-signal controls are:

```text
WAIT_DATA_PATH=.wait-local-agent/state.db
WAIT_ALLOWED_DOC_ROOT=examples/sample_docs
WAIT_SECRETS_BACKEND=env
WAIT_VAULT_PATH=.wait-local-agent/vault
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_HTTP_PROBING=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
WAIT_OFFLINE_MODE=false
WAIT_VECTOR_BACKEND=sqlite
WAIT_CONNECTOR_TIMEOUT_SECONDS=20
WAIT_SCHEDULER_ENABLED=true
WAIT_RATE_LIMIT_ENABLED=true
```

Provider, model, MCP, update, communication, tenant-map, and connector
variables are also read by `config.py`; see
[`environment-variables.md`](../reference/environment-variables.md) for the
source-of-truth warning and `.env.example` pointer.

## Authentication and demo mode

Demo mode is local convenience behavior. When `WAIT_DEMO_MODE=true`, the
runtime resolves requests as local admin for the demo path. Shared or
production-style use should set `WAIT_DEMO_MODE=false` and configure
`WAIT_ADMIN_TOKEN`, `WAIT_TECH_TOKEN`, and `WAIT_VIEWER_TOKEN`; the legacy
`WAIT_API_TOKEN` remains admin-equivalent. End-user support has a separate
fixed-scope token and client/user mapping.

Outbound connector calls require `WAIT_ALLOW_HTTP_PROBING=true`. Live
mutations also require `WAIT_ALLOW_WRITE_ACTIONS=true`, a supported action, and
the relevant approval gate.

