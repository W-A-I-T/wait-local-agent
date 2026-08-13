# Supervisor and child-agent delegation

WAIT can build a tenant-scoped delegation plan from existing persisted agent
definitions:

```text
POST /consultant/supervisor/plan
POST /consultant/supervisor/run
```

The CLI equivalent is:

```bash
wait-local-agent microsoft supervisor plan examples/consultant/supervisor-run.json
wait-local-agent microsoft supervisor run examples/consultant/supervisor-run.json --token "$WAIT_CLI_TOKEN"
```

The caller must name the child agents explicitly. WAIT revalidates that each
definition belongs to the requested tenant, preserves only dependencies among
the selected children, and assigns a bounded task/result contract. Child
agents receive only the tenant identifier, bounded supervisor task, and
structured results from completed dependencies.

The run endpoint/command executes the explicitly selected children in
dependency order through the existing `AgentService`. Each child run is
persisted and audited using the existing runtime; approval-required children
pause the supervisor response with a `pending_run_id`. Approve/resume that
child through the existing `/agent-runs/{run_id}/resume` route, then rerun the
same request with its completed run ID in `completed_run_ids` to continue with
the remaining children. Only bounded, redacted task and prior-result summaries
are passed as supervisor context, and cross-tenant context is rejected.
