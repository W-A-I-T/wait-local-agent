# Review

## Changed Files

- `src/wait_local_agent/connector_factory.py`
- `src/wait_local_agent/provider_adapters.py`
- `src/wait_local_agent/api/app.py`
- `ui/src/screens/ConnectorInstances.tsx`
- `ui/src/lib/connectorSetup.ts`
- `tests/test_connector_factory.py`
- `tests/test_provider_adapters.py`
- `ui/tests/ConnectorInstances.test.tsx`
- `ui/tests/connectorSetup.test.ts`
- `docs/getting-started/configuration.md`

## Risk Areas

- Confirm each provider's persisted credential shape against its existing
  client. ServiceNow intentionally uses Basic Auth password because that is
  what `servicenow.py` consumes; token auth is not invented here.
- Confirm Syncro subdomain-derived origins remain limited by the existing
  host allowlist and pinned-IP transport. Explicit Syncro base URL overrides
  still pass the same URL validation.
- Confirm normalized provider response envelopes without Halo/CW metadata use
  the existing `ConnectorReadResult` count and stable 200/failed fallback.
- Confirm all mappings and quarantine behavior continue through the existing
  `IngestionPoller` and store paths; no alternate ingestion route was added.
- Confirm no secrets enter `config_json`, API responses, logs, or validation
  error messages.

## Version & Compatibility Evidence

No version or API changes. The implementation reuses the provider modules'
current client APIs and the existing UI dependency set; `npm ls --depth=0`
reported Vite 8.2.2 and Vitest 4.1.11. No package, lockfile, migration, or
provider API version was changed. The remaining compatibility risk is limited
to full CI dependencies unavailable in this sandbox (`slowapi` and Bandit).

## Open Questions

- Claude should decide whether the full CI environment requires an additional
  API-level creation test for the new 422 validation path.

## Test Results

- Passed: `ruff check src tests`.
- Passed: targeted mypy for changed Python modules.
- Passed: Python bytecode compilation for `src` and `tests`.
- Passed: focused Vitest suite (2 files, 7 tests).
- Passed: UI TypeScript/Vite production build.
- Not run by contract: pytest and Playwright.
- Blocked by environment: full mypy due six missing `slowapi` imports; Bandit
  unavailable.

## Diff Summary

- Persisted Autotask, Syncro, and ServiceNow instances now build isolated,
  read-only clients from vault credentials, pass the existing network policy,
  and flow through the same normalized ticket ingestion path as HaloPSA and
  ConnectWise. The admin UI exposes the matching forms and cursor health.
  Environment-backed provider configuration remains unchanged as fallback.

## Requested Review Focus

- Narrow diff review, especially SSRF/allowlist enforcement, secret redaction,
  read-only write refusal, provider-field mapping, cursor status display, and
  preservation of the existing env fallback and route surface.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED after three scoped Codex fixes (test-helper default base_url
masking the syncro derivation branch; older ConnectorInstances test file not
aligned to the restructured screen; coverage top-up).

Security review: all three new providers flow through validate_provider_origin
with the instance allowlist (3 call sites), instance-built clients force
allow_write_actions=False, credential shapes are provider-specific frozensets
validated at create-time with clear errors, credentials only via vault refs.

Live smoke (branch build, port 18793, fernet vault): Syncro instance created
end-to-end with vault credential; bad credential shape rejected 422 with
"expected keys: api_key, subdomain"; ServiceNow/Autotask types recognized with
correct validation ordering (credentials-not-found before build).

Noted follow-up (not blocking, pre-existing): the create route accepts unknown
connector_type values as inactive rows (validation happens at build/sync), and
create-time credential validation covers only the three new types while
halopsa/connectwise validate at build — harmonize in a later slice.

Test evidence: full suite 95.02% vs 95% gate; mypy clean (290 files, CI-style
`mypy src tests`); bandit 0 findings; UI 369/369; factory/adapter suites 78/78.
