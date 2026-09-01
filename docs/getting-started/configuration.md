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
WAIT_DEMO_MODE=false
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

`WAIT_DEMO_MODE` defaults to `false`. A non-demo appliance fails to start
without `WAIT_ADMIN_TOKEN`, `WAIT_API_TOKEN`, or an active persisted
`msp_admin` principal credential. `WAIT_TECH_TOKEN` and `WAIT_VIEWER_TOKEN`
provide additional role-scoped access but do not replace the required admin
credential.

When `WAIT_DEMO_MODE=true` is explicitly selected, the runtime is bounded to a
demo client rather than acting as an unrestricted administrator. Provider
writes and deployments are disabled, and `/secrets` returns HTTP 403. The
principal model supports per-client roles and a global `msp_admin` role;
principal credentials are stored as SHA-256 hashes. End-user support has a
separate fixed-scope token and client/user mapping.

Outbound connector calls require `WAIT_ALLOW_HTTP_PROBING=true`. Live
mutations also require `WAIT_ALLOW_WRITE_ACTIONS=true`, a supported action, and
the relevant approval gate.

## Connector instances

HaloPSA, ConnectWise PSA, Autotask, Syncro, and ServiceNow can be configured as
persisted Connector Instances from **Integrations → Connector Instances**.
The instance stores non-secret configuration and a reference to the local
vault; credential material is never stored in `config_json` or returned by the
API. Existing environment-based configuration remains the bootstrap fallback
for appliance-wide provider access.

For instance setup, Autotask uses a base URL plus username, secret, and API
integration code. Syncro uses an API key and subdomain. ServiceNow uses its
instance URL plus username and password, matching the current Basic Auth Table
API client. Instance reads remain gated by `WAIT_ALLOW_HTTP_PROBING`, and the
instance origin must be listed in `WAIT_CONNECTOR_INSTANCE_ALLOWED_HOSTS`.
Connector polling is read-only and records health and last-successful-sync
state in the existing `sync_cursors` table.

## Microsoft sign-in

Microsoft Entra OIDC is configured from **Settings → People & Access**. The
optional first-boot defaults are `WAIT_OIDC_TENANT_ID`,
`WAIT_OIDC_CLIENT_ID`, `WAIT_OIDC_PUBLIC_BASE_URL`, and
`WAIT_OIDC_AUTO_PROVISION_CLIENT_ID`; saved database values take precedence.
The client secret is entered through the dashboard and stored only in the
Fernet vault. See the [Entra OIDC walkthrough](entra-oidc.md) for app
registration, redirect URI, and trusted-host requirements.
