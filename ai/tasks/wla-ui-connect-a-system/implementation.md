# Implementation

## Scope

Implemented the admin-gated Connector Instances "Connect a system" panel in
`ui/src/screens/ConnectorInstances.tsx`. The existing instance list, mapping
inspection, and sync action remain intact.

## Behavior

- Limits the create picker to HaloPSA and ConnectWise under PSA / Ticketing.
- Loads WAIT clients from `GET /clients` and excludes `__quarantine__`.
- Renders provider-specific non-secret configuration and credential fields;
  `client_secret` and `private_key` are masked password inputs.
- Validates ConnectWise `api_version` with `^[0-9]{4}\\.[0-9]+$`.
- Stores the provider credential JSON through `POST /secrets` first, using a
  stable `connector:{type}:{slug(display_name)}` reference.
- Creates the instance only after secret storage succeeds. The instance
  `config_json` contains only `base_url` and, for ConnectWise, `api_version`.
- Surfaces the demo-mode 403 vault notice and stops before the instance POST.
- Refreshes and selects the new instance after successful creation.

## Tests

Added Vitest coverage for provider field switching, secret masking, the
vault-first POST ordering and payload boundary, demo-mode 403 behavior,
quarantine exclusion, and invalid ConnectWise API versions.

The discover-companies, mapping, verification, and initial-sync workflow is
deferred as specified by the plan.
