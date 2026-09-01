# Review

## Changed Files

- Runtime/auth: `src/wait_local_agent/m365_auth.py`, `src/wait_local_agent/m365_graph.py`, `src/wait_local_agent/connector_factory.py`, `src/wait_local_agent/api/app.py`.
- Microsoft administrator seam: `src/packs/microsoft_admin/client.py`, `src/packs/microsoft_admin/router.py`.
- Tests: `tests/test_m365_auth.py`, both `ConnectorInstances` UI test suites.
- UI/docs: `ui/src/screens/ConnectorInstances.tsx`, `ui/src/lib/connectorSetup.ts`, `docs/connectors/m365.md`, `docs/getting-started/configuration.md`.
- Task artifacts: `implementation.md`, `review.md`, `status.json`.

## Risk Areas

- Profile precedence and ambiguity handling: client-scoped and MSP-wide profiles fail closed when their selected tier has multiple active records; unknown clients fall back to the MSP-wide tier, then environment settings.
- Token lifecycle: client credentials are created lazily, cached only in memory until `expires_on`, and acquisition errors are sanitized into the existing Graph/admin client error types. Static-token profiles preserve the legacy bearer behavior.
- Origin and transport security: profile config cannot supply a URL; Graph uses the fixed `graph.microsoft.com` origin and Azure authority uses the fixed `login.microsoftonline.com` authority. Instance clients retain the pinned transport.
- Secret handling: credential JSON is read from the vault, never copied into `config_json`, API instance responses, audit detail, or error messages.
- The existing TeamsGraph consumer remains environment-backed because the plan scope names `m365_graph.py` and the Microsoft administrator client; delegated/interactive auth remains out of scope.

## Version & Compatibility Evidence

- No dependency versions changed. The implementation reuses the repository-pinned `azure-identity==1.25.3` and its existing `ClientSecretCredential` path; `msgraph-sdk==1.61.0` is unchanged. UI validation ran with the repository-installed Vite 8.2.2, TypeScript 7.0.2, and Vitest 4.1.11.
- Microsoft’s current client-credentials guidance supports the `.default` Graph scope and the `login.microsoftonline.com` token authority; the Azure Identity API supports `ClientSecretCredential(..., authority=...)` and `get_token(*scopes)`. References: https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.clientsecretcredential?view=azure-python and https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow.
- `uv lock --check` could not run to completion because the sandbox cache/network is unavailable, but no dependency or lockfile edit was made. Remaining compatibility risk is limited to the repository’s pre-existing missing `slowapi` mypy stubs and the unavailable Bandit/full-suite gates.

## Open Questions

- Confirm in the final gate that the intended deployment path for client-scoped M365 profiles is the connector-instance ingestion path; the existing general M365 API routes historically have no client selector and therefore use the shared resolver’s default MSP-wide/environment selection.
- Run the prohibited-in-sandbox full pytest/coverage, Bandit, and gitleaks checks in CI or an approved environment.
- The branch is three commits behind the current remote `origin/main` snapshot after external repository movement; no rebase was performed to preserve the task checkout and user changes.

## Test Results

- Passed: Python compileall, Ruff, targeted mypy, focused M365 auth/factory smoke checks, `git diff --check`, TypeScript no-emit, and both ConnectorInstances Vitest files (22 tests).
- Blocked/unrun by contract/environment: full pytest and coverage, Playwright, Bandit, and complete `uv lock --check`.
- Full mypy remains blocked only by pre-existing missing `slowapi` stubs; no changed-module diagnostic was reported.

## Diff Summary

- Microsoft 365 now supports vault-backed app-registration or static-token profiles with lazy expiry-aware tokens, fixed origins, shared runtime resolution, and environment fallback. ConnectorInstances exposes the two credential modes without a base-URL field, and the factory/admin/Graph paths consume the same connection abstraction.

## Requested Review Focus

- Verify resolver precedence and same-tier ambiguity behavior, token cache expiry/error sanitization, reuse of the existing Azure Identity acquisition path, fixed-origin/pinned-transport enforcement, and that no credential value crosses into config/API/audit output.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED after scope enforcement and three fix round-trips.

MAJOR INCIDENTS (both rejected and restored from origin/main):
1. First run deleted the automation_discovery pack (~900 lines), gutted
   Consultant/SolutionDelivery screens, and reverted other recent main work.
2. Coverage top-up run deleted the entire agent_platform pack (4,506 lines)
   plus pyproject/Sidebar/routes wiring — despite an explicit scope guard in
   the dispatch prompt. Pattern across 3b/3c: Codex removes features recently
   merged to main. Mitigation: mandatory git diff --stat audit after every
   Codex return (now in the standing gate checklist).

The in-scope M365 work itself is sound: new m365_auth module (M365Connection
tagged-union credential modes client_credentials/static_token; lazy in-process
token cache with expires_on handling and injectable clock; ClientSecretCredential
via the existing azure-identity dependency loaded lazily; resolver seam with
fail-closed same-tier ambiguity matching #507's RMM pattern); m365_graph and
microsoft_admin consume one shared resolution seam; Graph/login endpoints are
fixed constants (SSRF surface removed rather than allowlisted); env static
token remains the fallback tier; token values never in logs/config/responses.

Fixes: per-type base_url parametrization (m365 requires none); bandit B105
nosec on the fixed Microsoft hostname; connectorSetup tier assertion updated
for the intended env->instance flip.

Test evidence: full suite 95.17% vs 95% gate; mypy clean (307 files); bandit 0;
UI 432/432; m365_auth 8/8 + top-ups; scope-audited final diff = 16 tracked
in-scope files + 2 new m365_auth files.
