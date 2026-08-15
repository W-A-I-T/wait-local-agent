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

