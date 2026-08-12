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
or deployed. The later Power Platform CLI/DevOps slice can consume these files
through `pac connector create` after explicit environment and deployment
approval.
