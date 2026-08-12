# MCP integration safety review

## Safety verdict

Acceptable as an opt-in Work IQ preview discovery adapter. The slice preserves
the generic MCP client's transport, request/response bounds, redaction, and
untrusted-metadata handling, while avoiding a product-facing remote execution
route.

## Permission and scope risks

Discovery is admin-only. Explicit calls are library-only, require a local
allowlist, and reject the documented mutation/action tool names. The adapter
does not create approval records, infer tenant scope, or authorize access from
remote annotations.

## Prompt injection exposure

Remote descriptions, schemas, annotations, and results remain untrusted and
are bounded/redacted by `McpClient`. They are returned for inspection only and
are never instructions for local tool selection or authorization.

## Transport/auth risks

The adapter requires explicit enablement, global HTTP probing, HTTPS, exact host
allowlisting, and an operator-acquired Microsoft Entra bearer token. Redirects
remain disabled. OAuth discovery/token exchange, token rotation, and TLS/DNS
pinning are not implemented in this slice.

## Missing tests and required remediations

Before production use, add tenant/user consent mapping, OAuth discovery and
refresh, token rotation, provider conformance tests against a controlled Work
IQ tenant, approval/evidence handling for any future action capability, and
cross-tenant security tests. Keep Work IQ preview claims and tool names current
with Microsoft's contract.
