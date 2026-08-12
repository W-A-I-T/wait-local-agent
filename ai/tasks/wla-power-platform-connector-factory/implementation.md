# Power Platform connector factory implementation

## Scope

- Added a deterministic OpenAPI 2.0 validator and artifact generator.
- Added API, CLI, and dashboard surfaces.
- Added API key, Basic, and supported OAuth 2.0 connection metadata.
- Added redaction, local-reference, HTTPS, size, operation, and tenant/RBAC
  validation tests.
- Added a PAC connector-create planner and approval-gated executor that
  consumes only validated factory artifacts.

## Existing primitives used

- Existing technician/viewer/admin RBAC and tenant-scope helper.
- Existing consultant API and audit event surface.
- Existing Typer CLI and React dashboard/API client.
- Existing approval-request, audit, and execution-result persistence.

## Explicit non-goals

The PAC execution path is deliberately bounded: it invokes only the fixed
`pac connector create` command after approval, with explicit environment,
artifact digest, timeout, and output controls. It does not implement solution
packaging/checker/import pipelines, provision Dataverse, resolve remote
references, probe the target API, or store connector credentials.
