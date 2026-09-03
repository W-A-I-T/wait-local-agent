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

The Solutions Architect dashboard includes the same planner and runner. Open a
selected blueprint's architecture view to inspect the dependency order and
bounded child context, then use **Plan delegation** before **Run delegation**.
The run control is disabled until a plan exists and requires an existing,
tenant-scoped ticket or entity ID. The API/CLI commands above remain available
for scripted handoffs.

The caller must name the child agents explicitly. WAIT revalidates that each
definition belongs to the requested tenant, preserves only dependencies among
the selected children, and assigns a bounded task/result contract. Child
agents receive only the tenant identifier, bounded supervisor task, and
structured results from completed dependencies.

Supervisor depth is explicitly one layer (`max_depth: 1`) and recursion is
disabled. There is no child-agent self-spawn or supervisor tool in the
delegated tool contract; selecting a child always names an existing persisted
agent definition and keeps execution inside the existing `AgentService`.

The run endpoint/command executes the explicitly selected children in
dependency order through the existing `AgentService`. Each child run is
persisted and audited using the existing runtime; approval-required children
pause the supervisor response with a `pending_run_id`. Approve/resume that
child through the existing `/agent-runs/{run_id}/resume` route, then rerun the
same request with its completed run ID in `completed_run_ids` to continue with
the remaining children. Only bounded, redacted task and prior-result summaries
are passed as supervisor context, and cross-tenant context is rejected.

The run request may set `max_retries` from 0 through 3. Only a failed child is
retried through the existing `AgentService.retry` limit, and every attempt is
returned with `supervisor_id`, child, sequence, attempt, and `retry_of_run_id`
lineage. A `cancel_run_id` may target only a queued or approval-paused child in
the same tenant and entity; cancellation is approval-aware and stops before any
later child is delegated. These controls do not bypass child permissions,
revision checks, or approval gates.

The canonical employee-onboarding child map is
`examples/consultant/employee-onboarding-child-agent-map.json`. Its target
tools describe the intended Microsoft/MSP handoffs, while its local fixture
tool is deliberately `ticket-triage`. This distinction is part of the demo
contract: the fixture proves bounded orchestration and audit lineage without
claiming live provider execution, deployable packaging, or deployment.
