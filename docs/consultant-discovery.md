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

When impact estimates are supplied, the response calculates monthly hours
saved from `monthly_runs * minutes_saved_per_run / 60` and optionally applies a
user-supplied hourly value. Risk review reports explicit state-change,
cross-tenant, approval, and failure-path factors. Both outputs are evidence
only and do not execute an agent, call a provider, or create a blueprint record.
