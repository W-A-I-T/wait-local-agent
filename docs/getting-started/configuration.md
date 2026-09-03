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

In non-demo mode, configured bootstrap tokens shorter than 16 characters emit
a startup warning without including the token value; startup still succeeds.
Use at least 32 random characters for `WAIT_ADMIN_TOKEN`, `WAIT_API_TOKEN`,
`WAIT_TECH_TOKEN`, and `WAIT_VIEWER_TOKEN`.

When `WAIT_DEMO_MODE=true` is explicitly selected, the runtime is bounded to a
demo client rather than acting as an unrestricted administrator. Provider
writes and deployments are disabled, and `/secrets` returns HTTP 403. The
principal model supports per-client roles and a global `msp_admin` role;
principal credentials are stored as SHA-256 hashes. End-user support has a
separate fixed-scope token and client/user mapping.

### Bootstrap token scope

The `WAIT_VIEWER_TOKEN` and `WAIT_TECH_TOKEN` bootstrap credentials authenticate
their role but retain appliance-wide read scope, including reads across all
clients. Use database principals with explicit client roles when access must be
limited to particular clients; do not treat a bootstrap viewer or technician
token as a per-client credential.

Outbound connector calls require `WAIT_ALLOW_HTTP_PROBING=true`. Live
mutations also require `WAIT_ALLOW_WRITE_ACTIONS=true`, a supported action, and
the relevant approval gate.

## Connector instances

HaloPSA, ConnectWise PSA, Autotask, Syncro, ServiceNow, and Microsoft 365 can be configured as
persisted Connector Instances from **Integrations → Connector Instances**.
The instance stores non-secret configuration and a reference to the local
vault; credential material is never stored in `config_json` or returned by the
API. Existing environment-based configuration remains the bootstrap fallback
for appliance-wide provider access.

For instance setup, Autotask uses a base URL plus username, secret, and API
integration code. Syncro uses an API key and subdomain. ServiceNow uses its
instance URL plus username and password, matching the current Basic Auth Table
API client. NinjaOne, Datto RMM, and N-able N-central use the existing
provider access token plus base URL and a non-secret client-to-provider map:
`organization_map_json`, `site_map_json`, or `org_unit_map_json`, respectively.
Microsoft 365 profiles store either an app-registration credential set
(`tenant_id`, `client_id`, and `client_secret`) or a legacy static access token
in the vault. Profile Graph and token origins are fixed to Microsoft’s
`graph.microsoft.com` and `login.microsoftonline.com`; they cannot be supplied
through `config_json`. Client-scoped profiles take precedence over MSP-wide
profiles, and an explicitly client-scoped request fails closed when that client
has no active connector instead of using an MSP-wide or environment credential.
Instance reads remain
gated by `WAIT_ALLOW_HTTP_PROBING`, and every instance
origin must be listed in `WAIT_CONNECTOR_INSTANCE_ALLOWED_HOSTS`. RMM graph
sync resolves an active client-scoped instance first, then an active MSP-wide
instance, then the existing environment provider, and finally the local
collector. Multiple active instances at the selected tier fail closed.
Connector polling is read-only and records health and last-successful-sync
state in the existing `sync_cursors` table.

Core connector reads honor the authenticated client scope from `client_id` or
`X-WAIT-Client-ID`. A bound client uses only its active client-scoped connector
instance; if none resolves, the API returns HTTP 409 with
`{"code":"client_scope_unavailable","client_id":"..."}`. Provider reads
without a client-scoped implementation return HTTP 409 with
`{"code":"client_scope_unsupported"}`. MSP administrators and demo mode keep
appliance-wide behavior when no client is requested.

## Microsoft sign-in

Microsoft Entra OIDC is configured from **Settings → People & Access**. The
optional first-boot defaults are `WAIT_OIDC_TENANT_ID`,
`WAIT_OIDC_CLIENT_ID`, `WAIT_OIDC_PUBLIC_BASE_URL`, and
`WAIT_OIDC_AUTO_PROVISION_CLIENT_ID`; saved database values take precedence.
The client secret is entered through the dashboard and stored only in the
Fernet vault. See the [Entra OIDC walkthrough](entra-oidc.md) for app
registration, redirect URI, and trusted-host requirements.
