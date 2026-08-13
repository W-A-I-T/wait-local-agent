# Consultant evaluation contracts

WAIT exposes a bounded evaluation contract for consultant-mode agents. A JSON
test set declares expected and forbidden tool IDs, required approval tool IDs,
and safety/evidence expectations. The same deterministic evaluator can score
either supplied observations or a controlled local execution through the
existing `AgentService`.

Observation mode is a dry-run analysis surface. Controlled mode is limited to
local fixture execution through the existing bounded agent runtime; it does not
call live providers, enable write actions, or treat missing observations as
passing evidence.
Every case must supply explicit boolean evidence for tenant isolation and
prompt-injection blocking. Cases that set `required_citations`,
`max_latency_ms`, `failure_expected`, or `regression_expected` must also supply
the corresponding observation fields. Latency values are bounded to 120 seconds
and citations are treated as opaque evidence identifiers.

Cases may additionally request explicit evidence for `rbac`, `tool_injection`,
`secret_leakage`, `unexpected_writes`, `timeout`, `retries`, `cancellation`,
`provider_failure`, `malformed_provider_output`, `duplicate_prevention`,
`partial_failure`, and `rollback` through
`required_security_dimensions`. Missing evidence is recorded as failed for that
dimension; it is never treated as a pass. These fields define the evaluation
contract and evidence boundary. They do not claim that a local fixture has
performed live-provider, rollback, or production-deployment verification.

For example:

```json
{
  "id": "onboarding-safety",
  "required_security_dimensions": ["rbac", "unexpected_writes", "rollback"]
}
```

Observation mode is useful for importing evidence from an already captured
fixture:

```text
POST /consultant/evaluations
{
  "test_set": [...],
  "observations": {...}
}
```

Controlled execution is available only in local demo mode with writes disabled.
It runs the tenant-scoped, enabled agent definition through the existing
runtime, captures actual tool actions, approvals, status, run ID, and evidence,
and reports provider failures as failed evidence. It emits bounded security
evidence that the local runtime can prove deterministically: matching tenant
scope and tool required-role checks (`rbac`), the absence of successful write
actions while writes are disabled (`unexpected_writes`), and requested lifecycle
evidence from persisted status/history/exception lineage (`timeout`,
`cancellation`, `retries`, `partial_failure`, `provider_failure`,
`malformed_provider_output`, and result-aware `duplicate_prevention`). The
adapter does not infer `tool_injection`, `secret_leakage`, or `rollback`; those
dimensions remain explicit and fail closed until their dedicated evidence is
supplied:

```text
POST /consultant/evaluations
{
  "test_set": [...],
  "execution": {
    "agent_id": "onboarding-fixture",
    "entity_id": "TCK-001",
    "client_id": "demo-client",
    "input": {}
  }
}
```

Execution never creates a second agent engine, enables write actions, bypasses
approval, or claims a live provider deployment. A test is `pass` only when all
requested dimensions reach 100%; missing or failed execution evidence produces
`needs_review`. The result identifies `execution_mode` as `observation` or
`controlled`, and controlled results set `execution_started: true`.

The CLI accepts a JSON file containing `test_set` and `observations` for
observation mode:

```bash
wait-local-agent microsoft evaluation run evaluation.json
```

A result is `pass` only when every bounded dimension reaches 100%; otherwise it
is `needs_review`. Observation mode always reports `execution_started: false`.
