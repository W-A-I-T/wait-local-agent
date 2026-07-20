# Review: adaptation-conn-azure

## Findings

No blocking issues found in the implemented connector path.

## Review Notes

- Azure connector mirrors the AWS connector shape: manifest/scope/config validation, preview/collect, `_collect_result`, `_config_limit`, `_session`, `_client`, per-resource record builders, `_result`, `_invalid_result`, `_asset`, `_observations`, and `_format_value`.
- Tests use injected fake sessions and monkeypatched SDK modules only. No live Azure calls are made.
- Connector is read-only by scope and implementation. It only calls list/read inventory APIs:
  - `compute.virtual_machines.list_all`
  - `storage.storage_accounts.list`
  - `network.network_security_groups.list_all`
  - `authorization.role_assignments.list_for_subscription`
- Per-resource Azure SDK errors are swallowed for the failing resource family only, matching the AWS connector behavior.
- Canonical assets and observations are deterministic and limited after sorting.

## Security Review

- No secrets were added.
- No shell execution, file writes, mutation APIs, or live network calls are used by tests.
- Runtime Azure access uses `DefaultAzureCredential` only when no injected session is provided.
- `subscription_id` can be supplied explicitly or through `AZURE_SUBSCRIPTION_ID`; tests do not rely on ambient credentials.

## Remaining Risk

- `uv.lock` was not refreshed because dependency resolution requires network access and DNS is blocked in this session.
- Full test suite and ruff could not be run in the managed environment for the same reason. Targeted connector tests passed with `PYTHONPATH=src`.
