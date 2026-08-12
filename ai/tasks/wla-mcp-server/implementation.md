# Implementation record

Implemented the first Microsoft Consultant Mode integration slice:

- Added `src/wait_local_agent/mcp_server.py` as a protocol-only adapter.
- Added authenticated `GET/POST /mcp` routes to the existing FastAPI server.
- Added opt-in `WAIT_MCP_ENABLED` and exact `WAIT_MCP_ALLOWED_ORIGINS`
  settings, disabled by default.
- Reused the existing bearer-token RBAC, `AgentService` catalog, and
  `SmartActionService` invocation path.
- Added role filtering, tenant binding, bounded requests, pagination, schema
  normalization, redaction, generic errors, and approval metadata.
- Documented the local integration surface in `docs/mcp.md`.
