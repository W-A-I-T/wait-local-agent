# Review

## Changed Files

- UI routes, Sidebar navigation, Microsoft Admin access hook, and focused route,
  hook, Sidebar, and capability-gate tests.
- Added `ui/src/screens/NotFound.tsx` and `ui/src/routes.test.tsx`.
- Updated task implementation, review, and status artifacts.

## Risk Areas

- `navAllowed` is intentionally broader than route `allowed`: it exposes the
  Microsoft Admin pack for any active principal grant, while the existing
  exact selected-client/global check still protects both Microsoft Admin
  routes.
- The Azure screen's existing API calls and implementation were not changed.

## Version & Compatibility Evidence

- No version or API changes. Validation used the checked-in compatible versions:
  React Router 7.18.2, React 19.2.8, Vite 8.2.2, and Vitest 4.1.11.
- `npm ci` completed from `ui/package-lock.json` without modifying the lockfile.
- Remaining warning: Vite reports the pre-existing config-loader notice for an
  extensionless `apiProxyRoutes` import; it is outside this task's scope.

## Open Questions

- None.

## Test Results

- Focused route/access/sidebar/gate tests: 4 files and 17 tests passed.
- Full suite with `--maxWorkers=2`: 56 files and 271 tests passed.
- Production build: passed.
- Default unrestricted-parallel full suite: the existing Sidebar test exceeded
  its 5-second timeout under local resource contention; no assertion failure
  occurred, and the same full suite passed with bounded workers.

## Diff Summary

- Unknown URLs stay on a NotFound screen; Azure Lighthouse is reachable and
  visible in Solutions for Microsoft Admin grantees; All clients no longer
  hides client-scoped Microsoft Admin pack navigation; route gates remain
  unchanged.

## Requested Review Focus

- narrow diff review

## Prior Execution Note

- 2026-08-31T00:24:59Z: an earlier Codex implementation attempt exited with
  status 143. The current implementation completed and passed bounded full
  suite/build validation.

## Claude review — 2026-08-30 (one issue)

Verification: build green; 270/271 tests pass. The one failure is
`Sidebar.test.tsx` "renders the product groups and keeps every destination
path for an authorized admin" — it TIMES OUT at the default 5000ms only under
full-suite load (passes in isolation; 5.5s when 56 files run in parallel).
Your changes added extra hook renders to that test path, tipping it over.

Fix (choose one, keep it minimal):
1. Preferred: reduce the per-assertion work in that test (e.g. one render +
   synchronous queries instead of repeated findBy* awaits), or
2. Pass an explicit timeout for that single test: `it("…", async () => {…}, 15000)`.

Do not touch production code. Run `cd ui && npm test -- --run` twice; both must
be fully green.
