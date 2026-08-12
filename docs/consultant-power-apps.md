# Consultant Power Apps and Dataverse artifacts

WAIT provides two bounded local-first surfaces:

```text
POST /consultant/power-apps/plan
POST /consultant/power-apps/build
```

The CLI equivalents are:

```bash
wait-local-agent microsoft power-apps plan examples/consultant/power-apps-plan.json
wait-local-agent microsoft power-apps build examples/consultant/power-apps-plan.json \
  --output power-apps-artifact.json
```

`build` validates the same tenant-scoped tables, fields, screens, and
connector references as the plan surface, then produces a deterministic local
artifact manifest containing:

- `dataverse/schema.json` table and column metadata;
- `canvas-app/manifest.json` screens, data sources, controls, and connector
  references; and
- a review README and explicit solution metadata.

The artifact is a builder handoff, not an `.msapp` file or an imported
Dataverse solution. It contains no credentials, does not call Microsoft
services, does not invoke `pac`, and does not start writes or deployment.
State-changing connector actions still require approval in the input contract.
