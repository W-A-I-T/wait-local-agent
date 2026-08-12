# Consultant agent monitoring

WAIT exposes a tenant-scoped agent health summary over the existing persisted
agent definitions and runs. It reports run counts, success/failure rates,
pending counts, last-run timestamps, definition versions, enabled state, and a
small health status. Run state payloads are not returned.

API:

```text
GET /consultant/monitoring/agents
```

CLI:

```bash
wait-local-agent microsoft monitoring agents --client-id acme
```

The monitoring surface is read-only and does not retry, resume, cancel, invoke,
or mutate agent runs. Non-admin API callers remain bound to their authenticated
tenant.
