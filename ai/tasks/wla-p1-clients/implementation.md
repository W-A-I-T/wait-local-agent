# Implementation — WLA-P1

Task: `wla-p1-clients`  
Branch: `codex/wla-p1-clients`  
Repository: `W-A-I-T/wait-local-agent`  
Scope: backend-only; `ui/` was not modified.

## What changed

- Added migration 2, `clients_and_connectors`, after the existing principals
  migration. It creates `clients`, `connector_instances`, and
  `client_connector_mappings`, including the `ux_ccm_verified` partial-unique
  index and the requested foreign keys.
- Added idempotent startup repairs. The reserved `__quarantine__` client is
  inserted with status `quarantine`, and existing non-null client IDs from
  `tickets` and `canonical_assets` are backfilled into the directory when
  those tables and columns exist.
- Added typed store records and accessors. Client and mapping reads use the
  existing `ClientScope` and `_client_scope_predicate`; connector instances
  remain MSP-level. Verified mapping conflicts are surfaced through a clear
  conflict exception, and the resolver returns `None` unless exactly one
  verified mapping exists.
- Added the new client, connector-instance, and mapping routes. Tenant reads
  fail closed; foreign client details return 404; connector-estate changes,
  client creation/status changes, and mapping verification require
  `msp_admin` or demo authority. Connector config JSON rejects credential-like
  fields and values; the existing Settings connector path is unchanged.
- Added migration, startup-repair, scope, partial-unique, resolver, secret
  rejection, and API smoke tests. Updated the existing migration expectations
  for version 2.
- Added targeted coverage tests for P1 fail-closed store accessors and client
  ID normalization, each connector-instance update field, unmapped and
  unverified resolution, the SQLite partial-unique integrity-conflict path,
  migration version/name validation, and API out-of-scope, missing-resource,
  no-tenant, and non-MSP-operator responses.
- Added customer-safe data-model documentation, the Unreleased changelog
  entry, and `admin` classifications for every new FastAPI route in the
  surface manifest.

## Files touched

- `src/wait_local_agent/models.py`
- `src/wait_local_agent/store.py`
- `src/wait_local_agent/api/app.py`
- `tests/test_spine_p0.py`
- `tests/test_principals.py`
- `tests/test_wla_p1_clients.py`
- `README.md`
- `docs/README.md`
- `docs/concepts/clients-and-connectors.md`
- `docs/ai-workflow/surface-coverage.json`
- `CHANGELOG.md`
- `ai/tasks/wla-p1-clients/implementation.md`

## Validation

The exact requested commands were attempted from this checkout. The checkout
did not initially contain `.venv`; the local ignored symlink used for the
commands points to the machine's existing project environment. That
environment has an editable install targeting the sibling
`/home/josephp/wait-local-agent` checkout, so the exact pytest command fails
during collection before exercising this checkout:

```text
$ .venv/bin/python -m pytest
ImportError: cannot import name '_backfill_scope' from 'wait_local_agent.api.app' (/home/josephp/wait-local-agent/src/wait_local_agent/api/app.py)
ModuleNotFoundError: No module named 'wait_local_agent.client_scope'
ModuleNotFoundError: No module named 'wait_local_agent.migrations'
!!!!!!!!!!!!!!!! Interrupted: 8 errors during collection in 6.16s !!!!!!!!!!!!!!!!
```

An editable install could not be repaired offline because the build backend
`hatchling>=1.24` was not available locally and network access is disabled.
With `PYTHONPATH=src`, the non-HTTP focused tests pass:

```text
..                                                                       [100%]
```

The full suite cannot progress past the same environment's TestClient issue:
even an unchanged trivial FastAPI app hangs on `TestClient(app).get('/')`.
The installed versions are Starlette `1.3.1` and httpx `0.28.1`; the test
client emits its warning that httpx2 is required. No coverage percentage was
claimed because the full suite did not complete.

Exact static-check result lines:

```text
$ .venv/bin/python -m mypy src tests
Success: no issues found in 206 source files

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/bandit -r src
Test results:
    No issues identified.
Total issues (by severity):
    Undefined: 0
    Low: 0
    Medium: 0
    High: 0
```

Migration rehearsal on a copied populated v1 database:

```text
tickets: before=2 after=2
ticket_status_history: before=2 after=2
canonical_assets: before=1 after=1
asset_observations: before=0 after=0
foreign_key_check: []
```

The surface inventory comparison reported:

```text
missing []
extra []
```

The direct endpoint smoke exercised create client, create connector
instance, create mapping, and verify mapping and reported:

```text
clients: client-a
connector_status: inactive
mapping_verified: 1
```

No PR was created and nothing was pushed. Human merge/deploy authority remains
unchanged.
