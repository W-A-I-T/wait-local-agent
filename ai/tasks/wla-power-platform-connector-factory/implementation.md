# Power Platform connector factory implementation

## Scope

- Added a deterministic OpenAPI 2.0 validator and artifact generator.
- Added API, CLI, and dashboard surfaces.
- Added API key, Basic, and supported OAuth 2.0 connection metadata.
- Added redaction, local-reference, HTTPS, size, operation, and tenant/RBAC
  validation tests.

## Existing primitives used

- Existing technician/viewer/admin RBAC and tenant-scope helper.
- Existing consultant API and audit event surface.
- Existing Typer CLI and React dashboard/API client.

## Explicit non-goals

This slice does not invoke `pac`, authenticate to Dataverse, create/update a
Power Platform connector, resolve remote references, probe the target API, or
store connector credentials. Those actions belong to the separately gated
Power Platform DevOps/deployment capability.
