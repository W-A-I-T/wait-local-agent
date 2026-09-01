# API Reference

The running FastAPI server publishes its generated OpenAPI documentation at
[`/docs`](http://127.0.0.1:8788/docs) and its OpenAPI JSON at
[`/openapi.json`](http://127.0.0.1:8788/openapi.json). Those endpoints are the
authoritative route and schema reference for the current build.

The route groups include health/settings, authentication, tickets and
end-user support, approvals/audit/events, knowledge, workflows and scheduled
jobs, agents and execution observability, smart actions and collectors,
connector status and provider-specific reads/writes, backups/secrets and
hardening, consultant/Microsoft preparation, MCP, reports, and pack/update
surfaces. All route behavior remains subject to RBAC, tenant filters, safety
flags, and approval requirements described in the concept and connector docs.

## Diagnostics and support

These appliance-wide routes require an administrator with MSP or appliance
scope. Client-bound administrators receive HTTP 403.

| Method and path | Behavior |
| --- | --- |
| `GET /diagnostics/summary` | Returns only allowlisted appliance facts, readiness states, and scrubbed failure metadata. |
| `POST /diagnostics/bundle/preview` | Lists fixed included sections and excluded data without writing a file. |
| `POST /diagnostics/bundle` | Builds a private deterministic ZIP and returns it with `X-Support-Bundle-SHA256`. |
| `POST /diagnostics/bundle/upload` | Records a local refusal and performs no network transfer. |

The optional request body for preview and bundle accepts `case_id`, which is
stored in the manifest only as a SHA-256 digest. The upload body accepts
`consent`; missing consent, offline mode, demo mode, and missing destination
configuration each fail closed. Configuration alone does not enable transfer.
Every API response carries a bounded, validated `X-Correlation-ID`.
