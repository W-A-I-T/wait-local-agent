# Power Platform custom-connector factory

WAIT can turn a supplied OpenAPI 2.0 document into two reviewable Power
Platform custom-connector artifacts:

- `apiDefinition.json`: a redacted, normalized OpenAPI 2.0 definition.
- `apiProperties.json`: deterministic connection-parameter and publisher metadata.
- `manifest.json`: a small summary containing the connector name, auth type,
  operation count, and warnings.

The factory is available to an authenticated technician at
`POST /consultant/connectors/power-platform`, in the CLI at:

```text
wait-local-agent consultant power-platform generate definition.json \
  --output-dir ./connector-artifact --token "$WAIT_CLI_TOKEN"
```

It is also available in the dashboard at `/connector-factory`.

The generator is intentionally offline and design-only. It does not probe the
described host, resolve remote `$ref` URLs, create a Dataverse row, call `pac`,
or store OAuth/API credentials. It accepts only HTTPS schemes, local `#/`
references, bounded paths/operations/parameters, and definitions under the
local safety limit of 950,000 bytes. It supports API key, Basic, and supported
OAuth 2.0 definitions; OAuth application/client-credentials flow is rejected.

Microsoft's connector import guidance currently requires OpenAPI 2.0 and a
definition smaller than 1 MB. The generated files are therefore import
artifacts for operator review, not a claim that a connector has been created
or deployed.

## PAC deployment planning and execution

An administrator can validate an artifact directory and produce a fixed PAC
plan with an explicit target environment:

```text
wait-local-agent consultant power-platform pac-plan ./connector-artifact \
  --environment https://org.crm.dynamics.com --token "$WAIT_ADMIN_TOKEN"
```

The API equivalents are:

- `POST /consultant/power-platform/pac/connector/create/plan` — technician
  plan generation.
- `POST /consultant/power-platform/pac/connector/create` — creates a pending
  approval request, or executes the exact approved plan as an administrator.

The plan accepts only the factory's `apiDefinition.json`, `apiProperties.json`,
and `manifest.json`; validates their format, local paths, bounded size, and
SHA-256 digests; and emits only the documented `pac connector create` argument
vector. It requires a GUID or HTTPS environment target and never relies on the
PAC active profile. The execution path uses an argument array with
`shell=False`, a bounded timeout/output, a sanitized environment, and no
credential arguments. A changed artifact, target, or solution name invalidates
the approval payload. If `pac` is absent, the result is explicitly
`not_configured`; WAIT does not silently fall back to another deployment path.

This remains a governed deployment boundary: planning is reviewable, external
mutation requires approval, and the current slice does not claim solution
packaging, solution-checker execution, Dataverse provisioning, or production
deployment automation.
