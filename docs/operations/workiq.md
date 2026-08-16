# Work IQ MCP adapter

Work IQ is an optional Microsoft 365 integration. Current Microsoft
documentation describes a path-based MCP surface with generic entity tools
(`fetch`, `create_entity`, `update_entity`, `delete_entity`, `do_action`, and
`call_function`), Copilot tools, and schema discovery. Microsoft also documents
the Work IQ CLI/MCP experience as generally available from June 16, 2026. See
the [Work IQ overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview),
[entity model](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/entity-model),
and [tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference).

WAIT currently exposes one governed smart action, `workiq-fetch`, through the
existing API, CLI, Agents catalog, and MCP server. It accepts a local
`client_id` plus up to ten relative Microsoft Graph paths and returns bounded,
redacted read results. The adapter permits only `/me/`, `/users/`, and `/sites/`
paths, blocks authentication and service-principal paths, and rejects
`$skip`/`$skiptoken` pagination parameters.

WAIT intentionally exposes only a read-only subset in this slice. Operation
risk is not inferred from a tool name alone: resource path, requested
operation, tenant scope, authenticated identity, request arguments, and the
local offline/path/operation policy are evaluated together by the deterministic
request classifier. It returns a bounded `read`, `write`, `action`,
`high-risk`, `blocked`, or `unknown` decision; only `read` can reach the MCP
client in this adapter. Tenant and identity context is used locally and is
not copied into the remote request body. Unknown or side-effecting operations
remain blocked rather than being guessed from remote metadata.

The classifier follows Microsoft's path-based entity model and policy boundary:
the selected generic tool, relative resource path, request content, signed-in
identity, and tenant policy are separate inputs to governance. See the
[Work IQ entity model](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/entity-model)
and [policy governance guidance](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp).

Configuration is optional:

```text
WAIT_WORK_IQ_MCP_ENDPOINT=
WAIT_WORK_IQ_MCP_ACCESS_TOKEN=
WAIT_WORK_IQ_MCP_TIMEOUT_SECONDS=20
WAIT_MCP_CLIENT_ALLOWED_HOSTS=
```

The endpoint and access token are kept server-side. A non-empty access token is
required whenever the MCP endpoint is set. If the endpoint has no token, WAIT
leaves Work IQ `not_configured`, does not create an MCP client, and makes no
unauthenticated outbound request. The access token must be acquired through an
externally governed Microsoft Entra flow; WAIT does not perform OAuth
acquisition in this slice. No Work IQ create, update, delete, action, Copilot
`ask`, binary retrieval, automatic retries, or broad path
enumeration is exposed. Unsupported operations remain unavailable rather
than being inferred from the remote tool catalog.
