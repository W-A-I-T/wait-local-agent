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
operation, tenant scope, authenticated identity, and arguments must remain
inside the local policy boundary. Unknown or side-effecting operations remain
blocked rather than being guessed from remote metadata.

Configuration is optional:

```text
WAIT_WORK_IQ_MCP_ENDPOINT=
WAIT_WORK_IQ_MCP_ACCESS_TOKEN=
WAIT_WORK_IQ_MCP_TIMEOUT_SECONDS=20
WAIT_MCP_CLIENT_ALLOWED_HOSTS=
```

The endpoint and access token are kept server-side. The access token must be
acquired through an externally governed Microsoft Entra flow; WAIT does not
perform OAuth acquisition in this slice. No Work IQ create, update, delete,
action, Copilot `ask`, binary retrieval, automatic retries, or broad path
enumeration is exposed. Unsupported operations remain unavailable rather
than being inferred from the remote tool catalog.
