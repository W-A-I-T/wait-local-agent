# Power Platform connector preparation

WAIT can validate and prepare a bounded custom-connector artifact from a JSON
OpenAPI 2.0 definition. Microsoft Power Platform's documented import contract
uses OpenAPI 2.0 and limits the uploaded definition to 1 MB; WAIT applies that
limit before producing an artifact.

The factory is metadata-only. It records the HTTPS host, action methods and
parameters, response status codes, and authentication scheme metadata. It does
not include API keys or tokens, acquire OAuth credentials, call the described
API, invoke `pac`, or deploy a connector.

CLI examples:

```bash
wait-local-agent microsoft connector validate openapi.json halo
wait-local-agent microsoft connector generate openapi.json halo > halo-connector.json
wait-local-agent microsoft connector package openapi.json halo > halo-package.json
```

Connector validation and generation are API/CLI only — not available in the
dashboard. Use the `validate` and `generate` commands above for the
review-only preparation flow.

The authenticated technician API exposes the same preparation boundary:

```text
POST /consultant/connectors/openapi/validate
POST /consultant/connectors/openapi/generate
```

Definitions must use HTTPS, contain at least one supported action with a unique
`operationId`, and cannot contain parameter defaults, examples, or credential-
like parameter names. The package output is explicitly `review_only`; connector
import and deployment through this factory are not implemented in this
repository.

WAIT also exposes a no-side-effect `pac` planning surface:

```bash
wait-local-agent microsoft solution status
wait-local-agent microsoft solution plan onboarding WAIT_Dev wait /workspace/onboarding
```

`status` checks whether the executable is discoverable on the local PATH without
starting it. `plan` emits the proposed `pac solution init`, `pack`, and `check`
arguments. It does not create directories, overwrite files, contact Dataverse,
or execute a subprocess.

This no-side-effect planning command is distinct from the staged solution
deployment surface. WAIT also exposes approval-gated solution stages through
`/consultant/solutions/deployment-approvals` and the corresponding
`microsoft solution deployment-plan`, `request-deployment-approval`, and
`execute-stage` CLI commands. That path can run fixed, shell-free `pac` stages
only after the documented local feature flags, workspace, executable, tenant
scope, approval, and promotion-evidence checks pass; see
[`docs/consultant-power-platform-deployment.md`](consultant-power-platform-deployment.md).

See Microsoft's [custom connector OpenAPI definition guidance](https://learn.microsoft.com/en-us/connectors/custom-connectors/define-openapi-definition)
for the external import contract.
