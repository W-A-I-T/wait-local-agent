# Implementation Notes

## Summary

- Added `ui/.oxlintrc.json` with React and TypeScript plugins, correctness and suspicious categories, and the requested ignore patterns.
- Wired `oxlint .` into the dashboard lint script, the UI CI job, and the release gate; aligned the contributor release-gate checklist and changelog.
- Fixed the reported source and test lint errors with small naming, dependency, JSX-key, and unused-value changes. Selected-client loaders now use `apiFetchForClient` so their client dependency remains explicit and the existing request scope is preserved.
- Kept the existing `oxlint` 1.81.0 package and lockfile changes; no additional dependency or lockfile update was made.

## Round 2

- Set `react/react-in-jsx-scope` to `off`; the project uses the automatic JSX runtime (`jsx: react-jsx`), so the 6,411 diagnostics were pure noise.
- Temporarily set Oxlint 1.81.0's separate `react/exhaustive-effect-dependencies` rule to `off` so its error-level diagnostics did not force behavior-changing dependency edits; the overlapping `react/exhaustive-deps` rule remained `warn`.
- Restored the original behavior at the four reviewed sites: `ConnectorBrowsePanel` uses `[activeList?.path, page, safePageSize]`, `MicrosoftAdmin` uses `[selectedRunbook?.runbook_id]`, `SmartActionDetail` computes `schemaFields(action.input_schema)` directly and resets on `[action.action_id]`, and `ResourceTable` keeps its reset and fetch effects separate.

## Round 3

- Set `react/exhaustive-effect-dependencies` to `warn` so the correctness diagnostics remain visible while preserving the required original dependency arrays.
- Oxlint reports 78 total warnings: 68 `react/set-state-in-effect`, 6 `react/exhaustive-deps`, and 4 `react/exhaustive-effect-dependencies`; it reports zero errors.
- The 68 `react/set-state-in-effect` findings remain warnings because this codebase systematically uses effects for async-load/reset synchronization and the findings exceed the documented false-positive threshold.

## Commands Run

- `cd ui && npx oxlint . -f json`: passed; 186 files, 0 errors, 78 warnings (68 `react/set-state-in-effect`, 6 `react/exhaustive-deps`, 4 `react/exhaustive-effect-dependencies`).
- `cd ui && npm run lint`: passed; the status-literals test file reported 2 passing tests.
- Targeted Vitest regression set: passed; 5 files and 27 tests.
- `cd ui && npm run test:coverage`: passed; 90 files and 541 tests. The UI coverage summary was 75.37% statements, 68.84% branches, 73.08% functions, and 76.94% lines.
- `cd ui && npm run build`: passed; TypeScript build and Vite production build completed. Existing Vite warnings remain for the native config-loader extension and a large output chunk.
- `python3 scripts/public_surface_audit.py`: passed.
- `git diff --check`: passed.
- Compatibility check: installed `oxlint` is 1.81.0 with Node `^20.19.0 || >=22.12.0`; installed TypeScript is 7.0.2 and the UI engine range includes the CI Node line. The current typescript-eslint support range remains below TypeScript 7, so it was not introduced.

## Files Touched

- Tooling and gates: `.github/workflows/test.yml`, `scripts/validate_release.sh`, `ui/package.json`, existing `ui/package-lock.json` task setup changes, and `ui/.oxlintrc.json`.
- Documentation: `CONTRIBUTING.md` and `CHANGELOG.md`.
- Dashboard implementation and tests: the changed files under `ui/src/app`, `ui/src/components`, `ui/src/lib`, `ui/src/screens`, `ui/src/surfaces/founder`, and `ui/tests`, plus `ui/src/api/scopedFetch.ts`.
- Task records: `implementation.md`, `review.md`, and `status.json`.

## Follow-Up

- Implementation validation is complete. The pre-existing Vite config-loader and bundle-size warnings are outside this lint task and should be handled separately if desired.
- The harness reports that the Kimi executable is unavailable, so the configured reciprocal review was not run; no substitute reviewer was used.
- No PR was created in this implementation turn because the request scoped the work to the local task branch and did not authorize external PR or merge actions.

- 2026-09-04T00:29:02Z: Codex gpt-5.6-luna completed successfully; repository verification is next.
