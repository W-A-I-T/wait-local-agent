# Work IQ MCP adapter

Work IQ is an optional Microsoft 365 MCP integration. Microsoft documents the
service as a preview MCP endpoint with a generic tool surface: entity paths
are passed to tools such as `fetch`, while `search_paths` and `get_schema`
provide runtime discovery. See Microsoft's [Work IQ overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview)
and [tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference).

WAIT currently exposes one governed smart action, `workiq-fetch`, through the
existing API, CLI, Agents catalog, and MCP server. It accepts a local
`client_id` plus up to ten relative Microsoft Graph paths and returns bounded,
redacted read results. The adapter permits only `/me/`, `/users/`, and `/sites/`
paths, blocks authentication and service-principal paths, and rejects
`$skip`/`$skiptoken` pagination parameters.

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
