# Power Apps and Dataverse planning

WAIT Local Agent can produce a tenant-scoped, metadata-only plan for a Canvas
App and its Dataverse tables. The plan is intended for consultant review and
handoff into a controlled Power Platform build process.

The plan endpoint is:

```text
POST /consultant/power-apps/plan
```

Technicians must provide the authenticated tenant and a bounded definition of
entities, screens, and connector-backed actions. Entity and field names are
validated as lower-case identifiers. Field types and screen modes are
allowlisted. Non-GET actions must explicitly declare `approval_required: true`.
Secret-like field names are rejected.

The response includes `deployment_started: false` and
`dataverse_write_started: false`. This slice does not connect to Dataverse,
create tables, publish an app, or transmit credentials. It returns a reviewable
artifact only; deployment remains a separate approved operation.

For local automation, place the request fields in a JSON file and run:

```bash
wait-local-agent microsoft power-apps plan plan.json
```

The Power Apps planner is API/CLI only — not available in the dashboard. The
command above emits the reviewable plan artifact.

The CLI emits the same JSON artifact as the API. Credentials and service-role
keys are not accepted as plan inputs.
