# Outbound MCP client

WAIT Local Agent includes an optional outbound Streamable HTTP MCP client for
remote discovery and explicit integration work. It is disabled by default and
does not automatically register remote tools in the local catalog.

## Configuration

```dotenv
WAIT_MCP_CLIENT_ENABLED=true
WAIT_MCP_CLIENT_URL=https://mcp.example/mcp
WAIT_MCP_CLIENT_TOKEN=<remote-bearer-token>
WAIT_MCP_CLIENT_NAME=WAIT Local Agent
WAIT_MCP_CLIENT_ALLOWED_HOSTS=mcp.example
WAIT_MCP_CLIENT_TIMEOUT_SECONDS=20
WAIT_ALLOW_HTTP_PROBING=true
```

The endpoint must use HTTPS, contain no embedded credentials, and resolve to a
host in `WAIT_MCP_CLIENT_ALLOWED_HOSTS`. The dedicated token may be backed by
the configured local vault. A missing host allowlist, disabled client, or
disabled HTTP probing blocks outbound traffic before a request is attempted.

## Discovery

Administrators can explicitly request remote tool discovery:

```text
GET /mcp/remote/tools
```

The response is bounded to 500 tools and 20 pages. Remote descriptions and
schemas are marked as untrusted metadata, normalized, truncated, and redacted.
They are not merged into `/tools` and cannot silently become local agent tools.

The reusable `McpClient.call_tool()` method supports an explicit named call for
future connector integrations. There is intentionally no generic HTTP call
route yet: remote write semantics, local approval records, tenant mapping, and
result evidence need a dedicated integration contract before remote execution
is exposed through the API.

Work IQ-specific authentication and behavior are not part of this generic
client slice.
