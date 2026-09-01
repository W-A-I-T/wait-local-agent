# Implementation Notes

## Summary

- Generalized persisted Connector Instance clients to Autotask, Syncro, and
  ServiceNow while retaining HaloPSA and ConnectWise behavior.
- Reused the existing factory SSRF path (`validate_provider_origin`, the
  instance host allowlist, and `PinnedIpTransport`) and forced every
  instance-built client to `allow_write_actions=False`.
- Added exact vault credential schemas and config validation. Syncro can derive
  its canonical `https://<subdomain>.syncromsp.com` origin; ServiceNow uses the
  current client's Basic Auth username/password contract.
- Added normalized ticket adapters and registered all five providers with the
  existing ingestion poller seam. The poller and `sync_cursors` storage needed
  no structural changes.
- Extended the admin Connector Instances form, provider metadata, per-instance
  sync status display, focused tests, and configuration documentation.
- Added creation-time validation for the three newly instance-backed
  providers, returning stable HTTP 422 messages without exposing credential
  values. Existing HaloPSA/ConnectWise creation compatibility was preserved.
- Added focused coverage tests for provider-specific credential/configuration
  validation, Syncro derived origins, provider URL suffix handling, successful
  validation/store-backed construction, and dropped records in the new
  provider adapters.

## Commands Run

- `ruff check src tests` — passed.
- Targeted mypy for the changed factory, adapter, and test modules — passed.
- `python -m compileall -q src tests` — passed using `.venv/bin/python`.
- `npm test -- --run tests/ConnectorInstances.test.tsx tests/connectorSetup.test.ts`
  — passed: 2 files, 7 tests.
- `npm run build` — passed with the existing Vite native-config and large
  chunk warnings.
- `npm ls --depth=0` confirmed the installed UI toolchain, including Vite
  8.2.2 and Vitest 4.1.11; no dependency or lockfile changes were needed.
- `mypy src tests` was attempted and is blocked by the environment's missing
  `slowapi` package imports in existing API files. `bandit -r src` was
  attempted but Bandit is not installed in the available environment.
- Pytest and Playwright were intentionally not run, per the task contract;
  Claude should run them in the dependency-complete validation environment.

## Files Touched

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
- `ai/tasks/wla-psa-instances/implementation.md`
- `ai/tasks/wla-psa-instances/review.md`
- `ai/tasks/wla-psa-instances/status.json`

## Follow-Up

- Run the full pytest coverage gate, Playwright flow, and Bandit in Claude's
  review environment. Confirm the full mypy gate after installing the repo's
  declared Python dependencies.
- No PR was created, committed, or pushed; the task contract assigns merge and
  final-gate authority to humans/Claude.
