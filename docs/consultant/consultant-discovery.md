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
GET  /consultant/discovery/sessions
GET  /consultant/discovery/sessions/{session_id}
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

The list and detail routes return only sessions matching both the authenticated
tenant and principal. They make an active session resumable after an operator
refresh and expose the bounded transcript for review. A completed session keeps
its resulting blueprint ID when one was created. Reading or resuming a session
does not execute tools, call providers, infer missing answers, or deploy a
solution.

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
catalog and includes locally configured connector surfaces when present. By
default this is a no-probe operation. A configured connector therefore remains
`configured` with an explicit limitation that reachability, authentication, and
authorization were not probed. An operator may explicitly request the existing
allowlisted, read-only connector health contracts with `{ "probe": true }`.
Only a positive provider health response promotes a tenant-bound system to
`authorized`; authentication, connectivity, malformed-response, and local
policy failures remain `permission-limited`, `unavailable`, or `unknown` with
the failure evidence retained. No write action is available through this probe.
When local HTTP probing is disabled, the request records `probe_requested` but
does not make a network call. An unknown customer declaration is `detected`,
not silently treated as an empty or supported environment. A connector
configured for another or unbound tenant is also `permission-limited`.

If the local connector health record is `failed` for a tenant-bound connector,
the projection is `unavailable` with the failure retained as a limitation. It
does not turn the failed provider into an empty system list or infer that the
provider is authorized.

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

When a guided session reaches its final required answer, its response also
includes the promoted `blueprint_id` and blueprint. The stateless bulk
promotion route remains available for explicit operator-controlled promotion
and enforces the same completion and tenant checks.
