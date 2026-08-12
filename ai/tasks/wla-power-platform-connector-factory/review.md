# Power Platform connector factory safety review

## Verdict

Safe as a local artifact-generation slice.

## Controls

- Input is bounded by serialized size, nesting, collection, path, operation,
  and parameter limits.
- Only OpenAPI 2.0 and HTTPS definitions are accepted.
- Remote `$ref` URLs are rejected; no network resolution or API probing occurs.
- Operation IDs and response descriptions are required and bounded.
- API keys, client secrets, token-like text, and other sensitive values are
  redacted before generated definitions are returned or written.
- OAuth application/client-credentials flow is rejected because the current
  custom-connector path does not support it.
- API generation requires technician access and a tenant scope; viewer access
  and cross-tenant requests are denied.
- Generation creates an audit event but does not create external state.

## Deferred risks

`pac connector create`, environment selection, Dataverse permissions, solution
packaging, deployment approvals, and post-import connector tests require a
separate production-infrastructure and deployment review.
