# Power Automate workflow plans

The existing WAIT workflow runtime can produce a review-only Power Automate
plan from a bounded trigger and action graph. The API is:

```text
POST /consultant/workflows/power-automate/plan
```

The CLI equivalent is:

```bash
wait-local-agent microsoft workflow plan flow.json
```

Each step has an identifier, display name, kind (`action`, `condition`, or
`approval`), optional existing WAIT tool reference, method, and approval flag.
Non-GET steps must declare approval. The output records the trigger and action
sequence in a Power Automate-oriented artifact, but remains explicitly
`export_status: review_only`.

This slice does not invoke `pac`, create connections, acquire credentials,
call Microsoft services, execute a flow, or deploy a solution. It is the safe
handoff artifact between the visual workflow design and a separately approved
Power Platform packaging/deployment process.
