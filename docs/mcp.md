# MCP server

WAIT Local Agent exposes a small, stateless Streamable HTTP MCP adapter over
the existing smart-action catalog. The adapter translates MCP JSON-RPC
messages; it does not create a second executor or bypass the local approval,
tenant, role, audit, or provider controls.

## Enablement and security

The endpoint is disabled by default. Enable it only on a deployment with
explicit tenant configuration and bearer tokens:

```dotenv
WAIT_DEMO_MODE=false
WAIT_MCP_ENABLED=true
WAIT_CLIENT_ID=acme
WAIT_TECH_TOKEN=<scoped-technician-token>
WAIT_VIEWER_TOKEN=<scoped-viewer-token>
WAIT_ADMIN_TOKEN=<scoped-admin-token>
WAIT_MCP_ALLOWED_ORIGINS=https://trusted.example
```

`WAIT_MCP_ALLOWED_ORIGINS` is an exact comma-separated allowlist. Requests
without an `Origin` header are accepted for non-browser clients; browser
origins must be listed exactly. Do not use a wildcard. Put the service behind
TLS and an authenticated reverse proxy when exposing it outside the local
host. OAuth authorization and remote tenant provisioning are not part of this
slice.

The endpoint is:

```text
POST /mcp
```

It accepts one JSON-RPC object per request. `GET /mcp` returns `405` because
this slice is request/response only and does not open a server-initiated event
stream. Requests other than `initialize` must include
`MCP-Protocol-Version: 2025-06-18` (the previous supported version is also
accepted).

## Supported methods

- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list` with numeric-string cursors and pages of at most 50 tools
- `tools/call`

The catalog is sourced from the existing `/tools` runtime. MCP filters it by
the caller's role. Non-admin callers must have a tenant bound by their
authenticated settings, and a requested `client_id` cannot escape that scope.

Tool metadata includes JSON Schema input/output shapes, risk and role metadata,
and read/write annotations. A write or approval-gated action is still routed
through `SmartActionService`; the MCP response reports `pending_approval` and
the persisted approval ID rather than executing the write. Results are
redacted before they leave the adapter, and failures use generic messages so
provider or secret details are not returned to the MCP client.

## Example

```bash
export WAIT_MCP_TOKEN='<scoped-technician-token>'

curl -sS http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer ${WAIT_MCP_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"local-client","version":"1"}}}'

curl -sS http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer ${WAIT_MCP_TOKEN}" \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

This is a local WAIT integration surface. A Microsoft client can consume a
remote Streamable HTTP MCP server when its tenant policy, authentication, and
network exposure are configured separately; this repository does not claim a
preconfigured Microsoft tenant connection.
