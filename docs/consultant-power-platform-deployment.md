# Power Platform deployment stages

WAIT can prepare a staged Power Platform solution deployment plan and create an
approval request for one stage at a time:

```text
POST /consultant/solutions/deployment-approvals
POST /consultant/solutions/deployment-approvals/{request_id}/execute
```

The plan contains a `build` stage (`pac solution init`, `pack`, and `check`)
followed by optional `dev`, `test`, and `prod` import stages. Targets must be
ordered in promotion order and contain HTTPS environment URLs without
credentials or query data.

Planning is metadata-only: every planned stage reports
`deployment_started: false`. A `test` approval requires normalized evidence
that the immediately preceding `dev` stage succeeded, including a SHA-256
artifact digest, a passing evaluation, passing governance, and rollback
metadata. A `prod` approval applies the same gate to the preceding `test`
stage. Missing or non-passing evidence is rejected before an approval request
is created.

The promotion evidence shape is intentionally bounded:

```json
{
  "source_stage": "dev",
  "source_status": "succeeded",
  "source_approval_request_id": 123,
  "artifact_digest": "sha256:<64 lowercase hex characters>",
  "evaluation": {"production_readiness": "pass", "case_count": 1},
  "governance": {"status": "pass"},
  "rollback": {
    "available": true,
    "strategy": "reimport_previous_package",
    "artifact_digest": "sha256:<64 lowercase hex characters>"
  }
}
```

For TEST and PROD, `source_approval_request_id` must identify an approved,
same-tenant approval for the immediately preceding stage. Its persisted
execution result must be successful and contain the same artifact digest; a
caller cannot promote by submitting a self-declared success record.

The CLI exposes the same boundary:

```bash
wait-local-agent microsoft solution deployment-plan examples/consultant/deployment.json
wait-local-agent microsoft solution request-deployment-approval examples/consultant/deployment.json --stage build
wait-local-agent microsoft solution execute-stage <approval-id>
```

Planning never invokes `pac`. Execution requires an approved stage request,
admin authority for the execute route/command, `WAIT_ALLOW_WRITE_ACTIONS=true`,
`WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true`, an authenticated `pac` executable
on `PATH`, and a pre-existing `WAIT_POWER_PLATFORM_WORKSPACE`. The output
directory must be inside that workspace. Commands use `shell=False`, fixed
argument positions, bounded timeouts, and redacted output. Credentials are
never accepted in the plan or approval payload.

Execution is intentionally one stage at a time so DEV, TEST, and PROD each
retain a separate approval and audit record. A failed stage stops the pipeline;
later stages are not started automatically.
