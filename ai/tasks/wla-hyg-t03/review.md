# Review

## Changed Files

- Added the dashboard oxlint configuration and connected the existing lint script to CI and the release gate.
- Updated dashboard source/test files only where oxlint reported errors, including hook dependency cleanup and explicit selected-client request scoping.
- Updated `CONTRIBUTING.md` and `CHANGELOG.md`; the workflow change is exactly one inserted line.

## Risk Areas

- Hook and effect edits were limited to dependency correctness, stable callbacks, reset sequencing, and preserving the selected-client header on loaders. No backend, authentication, authorization, billing, entitlement, migration, or data-boundary code changed.
- `apiFetchForClient` trims and validates the client identifier before adding `X-WAIT-Client-ID`, otherwise delegating to the existing `apiFetch`; it introduces no new secret or trust boundary.
- Oxlint reports 78 warnings and zero errors. `react/react-in-jsx-scope` is off because the automatic JSX runtime makes its 6,411 diagnostics false positives. Oxlint 1.81.0's separate `react/exhaustive-effect-dependencies` rule remains visible as a warning so the required original effect dependency arrays remain behavior-neutral; it reports 4 findings, while `react/exhaustive-deps` reports 6. `react/set-state-in-effect` remains a warning with 68 systematic async-load/reset findings.

## Version & Compatibility Evidence

- The task uses the already-present `oxlint` 1.81.0 package. Local metadata reports Node engines `^20.19.0 || >=22.12.0`; the UI's declared engine range includes the CI Node 22 line. TypeScript 7.0.2 is unchanged.
- The official [Oxlint configuration documentation](https://oxc.rs/docs/guide/usage/linter/config.html) confirms `.oxlintrc.json` auto-discovery, and the [Oxlint quickstart](https://oxc.rs/docs/guide/usage/linter/quickstart) documents the local package/script pattern used here.
- The official [typescript-eslint dependency matrix](https://typescript-eslint.io/users/dependency-versions/) currently supports TypeScript `<6.1.0`; the repository's TypeScript 7.0.2 therefore remains incompatible with that alternative. No dependency upgrade or API migration was introduced.
- Remaining compatibility risk is limited to future Oxlint rule changes and the existing Vite warnings noted below.

## Open Questions

- The configured reciprocal Kimi review could not run because the harness reports the Kimi executable is unavailable; no substitute reviewer was used. Existing Vite native-config-loader and large-chunk warnings remain outside scope.

## Test Results

- `npx oxlint . -f json`: passed, 0 errors and 78 warnings across 186 files.
- `npm run lint`: passed, including 2 status-literal tests.
- Targeted regression tests: passed, 5 files / 27 tests.
- `npm run test:coverage`: passed, 90 files / 541 tests; 75.37% statements, 68.84% branches, 73.08% functions, 76.94% lines.
- `npm run build`: passed.
- `python3 scripts/public_surface_audit.py`: passed.
- `git diff --check`: passed.

## Diff Summary

The dashboard now has a repeatable Oxlint gate while retaining automatic JSX behavior, selected-client request scoping, and existing test assertions. The CI and release paths run the same lint entry point before tests/build.

## Requested Review Focus

- Confirm hook/effect changes are behavior-neutral, especially loader reset timing and selected-client changes.
- Confirm the documented warning rules, automatic-JSX suppression, and visible effect-dependency diagnostics are justified by the codebase and required behavior.
- Confirm the workflow contains only the requested lint insertion.
