# Provider scope and request context

WAIT Local Agent keeps model-provider configuration at the appliance-wide
scope. The configured provider and model are shared runtime settings; they are
not a tenant authorization mechanism and they do not grant a provider access
to other clients.

Requests that include tenant data remain tenant-scoped by the runtime. The
runtime performs authentication, role checks, client filtering, approval
gates, redaction, and bounded payload construction before a configured model
provider is called. A remote provider is optional, operator-configured, and
denied in offline mode.

The API exposes these boundaries as `provider_scope=appliance-wide` and
`context_scope=tenant-scoped` in `GET /settings/providers`. The Settings screen
shows the same evidence. Provider health is readiness evidence for the
configured model-list endpoint; it is not an availability or SLA claim.
