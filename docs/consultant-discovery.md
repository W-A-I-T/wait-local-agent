# Consultant discovery intake

WAIT provides a deterministic discovery intake at:

```text
POST /consultant/discovery
```

The CLI equivalent is:

```bash
wait-local-agent microsoft discovery assess discovery.json
```

The intake asks for explicit evidence about the business goal, users,
knowledge, systems, reads, changes, approvals, failure handling, licenses,
data location, and whether data may leave the tenant. Missing answers remain
missing; the service does not infer a system, permission, license, risk level,
or deployment target.

The governed environment projection is available at:

```text
POST /consultant/environment-discovery
```

It matches customer-declared systems only to the existing local connector
catalog and includes locally configured connector surfaces when present. This
operation does not call a provider. A configured connector therefore remains
`configured` with an explicit limitation that reachability, authentication, and
authorization were not probed. When local HTTP probing is disabled, the result
is `permission-limited` and says that provider authorization is unknown. An
unknown customer declaration is `detected`, not silently treated as an empty or
supported environment. A connector configured for another or unbound tenant is
also `permission-limited`.

The discovery response includes the same environment evidence in its
`blueprint_candidate.environment` field. A parsed Solution Blueprint may retain
these records, and the architecture view keeps any status below reachable,
authenticated, or authorized as an explicit review item. No environment record
claims live provider success.

When impact estimates are supplied, the response calculates monthly hours
saved from `monthly_runs * minutes_saved_per_run / 60` and optionally applies a
user-supplied hourly value. Risk review reports explicit state-change,
cross-tenant, approval, and failure-path factors. Both outputs are evidence
only and do not execute an agent, call a provider, or create a blueprint record.
