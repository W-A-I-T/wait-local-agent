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

After a successful approved execution, the local `build` stage continues to
report `deployment_started: false`; a non-build stage reports
`deployment_started: true` when its PAC command ran. This records the local
execution boundary and does not by itself prove provider-side import success
or production deployment.

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
and a pre-existing `WAIT_POWER_PLATFORM_WORKSPACE`. By default WAIT resolves
`pac` from `PATH`. Set `WAIT_PAC_PATH` to an explicit executable file when the
CLI is installed elsewhere; `pac` commonly installs at `~/.dotnet/tools/pac`,
which may not be on `PATH`. A configured path must be a regular executable file
and must not be a symlink. The output directory must be inside that workspace.
Commands use `shell=False`, fixed argument positions, bounded timeouts, and
redacted output. Credentials are never accepted in the plan or approval
payload. Execution is blocked when the CLI is older than the required minimum
version (`2.4.1`) or when its version cannot be determined.

After PAC completes, WAIT validates the expected solution archive before
recording success: it must be a readable, bounded ZIP inside the configured
workspace with safe member paths, no duplicate, encrypted, or symlink entries,
and valid member checksums. The SHA-256 digest is recorded only after that
validation. A valid local archive still proves package integrity, not provider
import success or production deployment.

Execution is intentionally one stage at a time so DEV, TEST, and PROD each
retain a separate approval and audit record. A failed stage stops the pipeline;
later stages are not started automatically.

## Rollback execution boundary

The deployment runtime includes a separate `execute_power_platform_rollback`
primitive for an explicitly approved target stage. It accepts only the
`reimport_previous_package` strategy, requires a prior ZIP whose bounded
contents and SHA-256 digest match the rollback evidence, and invokes the same
fixed `pac solution import` command with `shell=False`. Output is redacted and
reports PAC success or failure; validating the ZIP alone never reports a
provider rollback as successful.

Rollback requests are now exposed through the same approval and audit boundary:

```text
POST /consultant/solutions/rollback-approvals
POST /consultant/solutions/rollback-approvals/{request_id}/execute
```

The CLI exposes the equivalent commands:

```bash
wait-local-agent microsoft solution request-rollback-approval rollback.json --stage dev
wait-local-agent microsoft solution execute-rollback <approval-id>
```

The request path validates the artifact and digest before creating a pending
approval. The execute path requires an approved request and admin authority,
re-validates the stored evidence and artifact, records the bounded result in
the approval and audit records, and never chooses an artifact automatically.
It does not automatically roll back a failed stage or bypass the existing
write/deployment flags. A successful local `pac` return code is still only
provider-command evidence; live tenant rollback verification remains an
external boundary.
