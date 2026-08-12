# Implementation record

- Added `src/wait_local_agent/mcp_client.py`.
- Added opt-in outbound MCP settings and vault-backed token configuration.
- Added admin-only `GET /mcp/remote/tools` discovery.
- Added bounded pagination, response/request limits, safe endpoint validation,
  JSON-RPC validation, redaction, and untrusted metadata markers.
- Added focused client tests and documented the intentionally deferred generic
  remote call API.
