# WAIT MCP server

WAIT Local Agent exposes a bounded Model Context Protocol (MCP) server at
`POST /mcp`. This is the first MCP vertical slice: it publishes the existing
WAIT smart-action catalog and routes calls through `SmartActionService`. It
does not add a second execution engine or claim to be a Power Platform,
SharePoint, or deployment platform.

The endpoint implements the MCP lifecycle plus `tools/list` and `tools/call`
over JSON-RPC 2.0. Clients must initialize a session, send
`notifications/initialized`, and include the returned `MCP-Session-Id` on
subsequent requests. The implementation accepts protocol versions
`2025-11-25` and `2025-03-26`, advertises the current version, caps request and
result sizes, paginates the catalog, and returns tool failures as MCP tool
errors. See the [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
and [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
specifications for the protocol contract.

## Authentication and tenant scope

Every request is authenticated with WAIT's existing bearer-token RBAC. A
technician or administrator is required for `tools/call`; viewers can inspect
the protocol only if they hold a valid session but cannot invoke tools. The
authenticated tenant is the default `client_id` scope. Non-admin callers may
not request another tenant, and MCP clients never supply provider credentials
or provider asset identifiers as an authority shortcut.

Calls reuse the existing smart-action approval, provider-readiness, audit,
redaction, and write-action gates. Approval-required actions create the same
pending approval result used by the REST and CLI surfaces; MCP does not bypass
approval by setting an internal approval flag.

The endpoint follows the local HTTP security boundary described by the
[MCP transport guidance](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports):
an `Origin` is checked against the request origin, localhost, or
`WAIT_MCP_ALLOWED_ORIGINS`. Configure additional browser origins as a
comma-separated list. Tokens remain server-side and must never be put in
client-side bundles.

## Optional MCP client framework

`wait_local_agent.mcp_client.McpClient` provides the matching client-side
protocol layer for future external MCP integrations. It is transport-injected
for deterministic tests, validates HTTPS/local-only HTTP endpoints, refuses
embedded URL credentials, bounds requests/responses and catalog pagination,
and keeps bearer tokens in request headers. It supports initialize,
`notifications/initialized`, `tools/list`, and `tools/call`; it does not yet
register a provider or persist remote credentials.

## Minimal request sequence

```http
POST /mcp
Authorization: Bearer <WAIT technician token>
Content-Type: application/json
Accept: application/json, text/event-stream

{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"example-client"}}}
```

Use the returned `MCP-Session-Id`, then send:

```json
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

List tools with `tools/list`. Tool names use the `wait.` namespace, for
example `wait.ticket-triage`. Invoke a read action with `tools/call`:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "wait.ticket-triage",
    "arguments": {"ticket_id": "TCK-123"}
  }
}
```

## Current boundaries

- The server is local-first and bounded. The client framework is present for
  future integrations, Work IQ exposes only its bounded read adapter, and
  Power Platform connector, Power Apps, Power Automate, Copilot Studio
  handoff, and staged PAC preparation remain separate review surfaces.
- The current transport returns JSON responses for POST requests. SSE
  streaming, resumable streams, and MCP resource/prompt surfaces are not
  implemented.
- Sessions are process-local and bounded. Restarting the appliance expires
  them; clients must initialize again.
- Tool catalog capabilities are inherited from WAIT's existing registry. A
  provider that is not configured remains unavailable, and unsupported writes
  remain unavailable.
- Work IQ access is optional and preview-only. WAIT currently exposes only the
  bounded `workiq-fetch` read action through the existing smart-action
  catalog. Configure an externally acquired Entra access token with
  `WAIT_WORK_IQ_MCP_ACCESS_TOKEN`; automatic OAuth acquisition is not
  implemented.
