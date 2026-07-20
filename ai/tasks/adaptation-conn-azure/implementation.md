# Implementation: adaptation-conn-azure

## Summary

Implemented a read-only Azure inventory connector at `src/wait_local_agent/cloud_connectors/azure.py`, mirroring the structure and result contract of `src/wait_local_agent/cloud_connectors/aws.py`.

The connector provides:

- `manifest()`, `scope()`, `validate_config()`, `preview()`, and `collect()` methods.
- Fallback Azure SDK exception classes for environments where SDK packages are not installed.
- Injected `session.client(service_name)` support for tests and controlled callers.
- SDK-backed client construction using `DefaultAzureCredential` and `AZURE_SUBSCRIPTION_ID` / `subscription_id`.
- Read-only inventory collection for Azure VMs, storage accounts, network security groups, and role assignments.
- Canonical assets, per-attribute observations, deterministic sorting, preview/default limit behavior, and limit-zero short-circuit behavior.
- Per-resource-type SDK error isolation so one failing Azure service does not fail the full inventory.

Updated `src/wait_local_agent/cloud_connectors/__init__.py` to export `AzureInventoryConnector`.

Pinned Azure SDK dependencies in `pyproject.toml`:

- `azure-identity==1.25.3`
- `azure-mgmt-authorization==4.0.0`
- `azure-mgmt-compute==38.0.0`
- `azure-mgmt-network==30.2.0`
- `azure-mgmt-storage==25.0.0`

Version evidence was checked against public package metadata on 2026-07-20. `azure-mgmt-authorization==4.0.0` is the latest stable release, with newer 5.0.0 builds still beta/pre-release. The other pins use current stable releases visible in package metadata.

## Tests

Added `tests/test_azure_connector.py` with mocked SDK/fake-session coverage. No live Azure calls are made.

Covered:

- Manifest and scope metadata.
- Canonical asset mapping for all supported Azure resource types.
- Observation generation.
- Preview and explicit limit handling.
- Limit-zero no-client short circuit.
- Invalid config handling.
- Per-resource error isolation.
- Missing ID skipping.
- SDK session construction via monkeypatched Azure modules.
- Date/datetime formatting.

## Validation Run

Passed:

```bash
PYTHONPATH=src pytest tests/test_azure_connector.py
# 20 passed in 0.05s

PYTHONPATH=src pytest tests/test_aws_connector.py tests/test_azure_connector.py
# 42 passed in 0.05s

python3 -m py_compile src/wait_local_agent/cloud_connectors/azure.py tests/test_azure_connector.py src/wait_local_agent/cloud_connectors/__init__.py
```

Attempted but blocked by environment:

```bash
uv run pytest tests/test_azure_connector.py
uv run ruff check src/wait_local_agent/cloud_connectors/azure.py tests/test_azure_connector.py src/wait_local_agent/cloud_connectors/__init__.py pyproject.toml
```

`uv` could not fetch dependencies because DNS/network access is blocked in this session.

Attempted full suite:

```bash
PYTHONPATH=src pytest
```

Collection failed because this shell does not have project dependencies installed (`slowapi`, `apscheduler`, etc.), and `uv` could not install them due to the same network/DNS block.

## Notes

`ai/tasks/adaptation-conn-azure/plan.md` was not present in `/home/josephp/wla-azure` or `/home/josephp/Ai-workflow-Personal-Computer`, so implementation followed the explicit task instruction and the existing AWS connector/test contract.
