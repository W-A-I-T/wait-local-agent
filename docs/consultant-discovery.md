# Consultant discovery intake

WAIT provides a deterministic discovery intake at:

```text
POST /consultant/discovery
POST /consultant/discovery/promote
```

The CLI equivalent is:

```bash
wait-local-agent microsoft discovery assess discovery.json
```

For progressive intake, use the persisted guided session routes:

```text
POST /consultant/discovery/sessions
POST /consultant/discovery/sessions/{session_id}/turn
```

The session start accepts an optional opening business statement and explicit
answers. Each turn names one returned question field and supplies its answer.
The response returns `next_question`, `unanswered`, `assistant_message`, and a
bounded transcript. Sessions are scoped to the authenticated tenant and
principal, persist locally in SQLite, and emit audit events. The transcript is
bounded evidence of user answers and prompts; it does not contain hidden model
reasoning. A completed question sequence still does not imply that required
evidence is sufficient for architecture.

The intake asks for explicit evidence about the business goal, users,
knowledge, systems, reads, changes, approvals, failure handling, licenses,
data location, and whether data may leave the tenant. Guided questions also
cover the current process, owners, approvers, sensitive operations, compliance,
data residency, APIs, existing automation, channels, expected volume, business
value, success measures, and rollback expectations. Missing answers remain
missing; the service does not infer a system, permission, license, risk level,
or deployment target. The stateless route remains available for bulk or
fixture-based intake.

When a candidate is promoted into a parsed `SolutionBlueprint`, its explicit
answers may be retained under the optional `discovery` field. That evidence is
validated for bounded shapes, tenant-safe content, and secret material before
the blueprint can be persisted.

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

`POST /consultant/discovery/promote` is the explicit review boundary between
completed discovery and a persisted solution blueprint. It requires the
tenant-scoped `client_id`, a human-supplied `solution_name`, an explicit
`risk` (`low`, `medium`, or `high`), and the completed discovery `answers`.
The server recomputes discovery and refuses promotion while required answers
are missing. Approval labels from discovery are normalized into bounded
blueprint identifiers (for example, `Assign license` becomes
`assign_license`), while the original labels remain in the stored discovery
evidence. Promotion records the blueprint and audit event only; it does not
start agent execution, connector calls, provider operations, or deployment.
