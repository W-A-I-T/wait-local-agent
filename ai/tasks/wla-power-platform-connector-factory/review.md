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
- PAC plans validate the exact three local artifacts and bind their SHA-256
  digests into the approval payload.
- PAC execution requires an administrator-approved request, uses an argv list
  with `shell=False`, explicit HTTPS/GUID environment targeting, a bounded
  timeout/output, and a credential-filtered child environment.
- Changed artifacts or targets cannot be executed under an old approval.

## Deferred risks

Dataverse permissions, solution packaging, solution checker, import pipelines,
and post-import connector tests remain separate deployment capabilities. A
real PAC installation and Dataverse environment are required for live
execution; automated tests use a mocked process and never mutate Microsoft
state.
