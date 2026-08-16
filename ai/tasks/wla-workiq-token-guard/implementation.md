# Implementation

Implemented the Work IQ token guard in `WorkIqClient`.

Changes:

- Auto-created `McpClient` instances now require both a configured endpoint
  and a non-empty, non-whitespace access token.
- Endpoint-only configuration remains `not_configured`; no MCP client is
  constructed and no unauthenticated outbound request can occur.
- Injected `mcp_client` instances continue to work, including when settings
  contain an endpoint without a token.
- Added regression coverage for empty and whitespace-only tokens, successful
  injected-client use, and preserved configured-endpoint creation behavior.
- Documented the token requirement in the Work IQ operations guide, security
  model, and Unreleased security changelog.

Validation results will be recorded here after the required commands complete.
