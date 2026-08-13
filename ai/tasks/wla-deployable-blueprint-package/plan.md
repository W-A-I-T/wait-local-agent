## Task ID

`wla-deployable-blueprint-package`

## Goal

Add a deterministic, bounded, credential-free Power Platform package bridge
that converts validated WAIT consultant artifacts into an official YAML
solution source tree suitable as `pac solution pack --folder` input. The
package and its materialization must remain local-source operations: they must
never imply provider import, live verification, or deployment success.

The package must be reachable from the onboarding fixture, delivery plan, API,
and CLI while preserving tenant isolation, secret rejection, approval/write
gates, workspace confinement, and truthful status flags.

## Constraints

- Start from `origin/main`; keep the implementation on the dedicated task branch.
- Use the official Power Platform YAML source-control layout because modern
  flows and canvas apps are not supported by the legacy XML layout.
- Keep the builder pure and deterministic: canonical JSON, SHA-256 digests,
  UUID5 component IDs, no timestamps, randomness, PAC invocation, or provider calls.
- Add an explicit bounded `output_directory` to the builder contract so the PAC
  command plan and materialization target are digest-bound.
- Reject credentials, secret-like values, tenant mismatches, unsafe paths,
  traversal, symlinks, control characters, oversized content, and excessive files.
- Materialization is gated by `Settings.allow_write_actions`, writes only below
  `WAIT_POWER_PLATFORM_WORKSPACE`, and returns a blocked result when gated off.
- Every build/materialization result keeps `execution_started: false` and
  `deployment_started: false`; `deployable: true` means packable local source only.
- Preserve the existing review bundle as `deployable: false`; expose the new
  deployable-source artifact separately.
- Do not invoke PAC or Microsoft APIs and do not alter approval, promotion, or
  rollback contracts.
- Use Python 3.12 standard-library additions only; no dependency changes.
- Keep coverage at or above the existing 95% threshold and add public exports.

## Acceptance Tests

- Identical inputs produce identical package and per-file digests; changing an
  artifact changes the package digest.
- The emitted YAML tree contains solution/publisher manifests, component lists,
  Dataverse sources, connector sources, and supported flow metadata under the
  documented directories; unsupported binary canvas content is explicit.
- Validation re-derives all file/package digests, caps, tenant scope, state flags,
  credentials, and safe paths.
- Materialization is blocked without `allow_write_actions`, succeeds inside a
  pre-created workspace when enabled, rejects workspace escapes and symlinks,
  and verifies on-disk digests.
- The PAC plan's `--folder` is the validated materialization directory.
- Onboarding exposes a deployable package and digest without changing its live
  provider, execution, approval, or deployment boundaries.
- Delivery output keeps the review bundle non-deployable and links the separate
  deployable-source digest.
- API build/validate is tenant-scoped to technician access; materialization is
  admin-only and write-gated.
- CLI package/materialize commands emit bounded JSON and honor the same gates.
- Targeted tests, full pytest with coverage >=95%, Ruff, mypy, Bandit, and the
  public-surface audit pass.

## Version & Compatibility Evidence

- No version or dependency changes expected.
- PAC YAML source-control support requires Microsoft.PowerApps.CLI 2.4.1 or
  newer; document this prerequisite without invoking PAC in tests.
- Preserve Python 3.12, the existing `pyproject.toml`, lockfile, API contracts,
  deployment plan command shape, and existing tenant/RBAC behavior.

## Files Expected

- `src/wait_local_agent/power_platform_package.py`
- `tests/test_power_platform_package.py`
- `src/wait_local_agent/employee_onboarding_demo.py`
- `src/wait_local_agent/delivery_plan.py`
- `src/wait_local_agent/power_platform_deployment.py`
- `src/wait_local_agent/api/app.py`
- `tests/test_consultant_routes.py`
- `src/wait_local_agent/cli.py`
- `tests/test_cli.py`
- `docs/consultant-power-platform-package.md`
- `docs/status.md`, `ROADMAP.md`, `docs/enterprise-validation-matrix.md`, `README.md`

## Agent Ownership

- `owner`: `codex`
- `allowed_implementer`: `codex`
- `orchestrator`: `claude`
- `implementer_model`: `gpt-5.6-luna`
- `implementer_reasoning_effort`: `high`
- `root_model`: ``
- `root_reasoning_effort`: ``
- `assigned_file_ownership`: `src/wait_local_agent/power_platform_package.py`,
  the listed integration/test/docs files, and this task folder only.
- `blocked_paths`: unrelated modules, UI files, migrations, secrets, production
  infrastructure, and provider execution code outside the listed helper changes.
- `parallel_safe`: `true`
- `required_cross_family_reviewer`: `kimi`
- `final_gate_required`: `true`

## Out Of Scope

- Live provider DEV/TEST/PROD verification, read-back, import, or deployment.
- Binary `.msapp` synthesis or unsupported Dataverse/provider-only components.
- PAC invocation, Microsoft API calls, credentials, licensing, or environment
  authorization.
- Changes to approval, promotion-evidence, rollback, or deployment execution
  semantics.
- New dependencies, broad refactors, UI redesign, or unrelated documentation cleanup.

## Handoff To

Set the next owner to `codex` for elevated implementation. After verification,
route to `kimi` for read-only cross-family review, then `claude` for the final
elevated gate; a human retains merge and deployment authority.

## Review Focus

- Confirm YAML layout and PAC folder semantics are truthful and compatible.
- Confirm deterministic UUID5/digest construction has no time/random inputs.
- Confirm tenant isolation and credential/secret rejection across every composed artifact.
- Confirm materialization cannot escape the configured workspace and refuses symlinks.
- Confirm write gating is fail-closed and never changes execution/deployment flags.
- Confirm review-only and deployable-source artifacts remain distinct.
- Confirm API role checks, CLI scope checks, bounded errors, docs, and public-surface exports.
