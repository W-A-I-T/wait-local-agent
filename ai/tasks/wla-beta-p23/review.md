# Review

## Changed Files

- `ui/src/components/AgentToolPicker.tsx`
- `ui/src/screens/Agents.tsx`
- `ui/src/api/types.ts`
- `ui/src/styles.css`
- `ui/tests/Agents.test.tsx`

## Risk Areas

- Client-side prefix classification sends unknown tool IDs to Core / ticket intelligence;
  known connector prefixes are explicitly ordered and tested.
- Teams joins Microsoft 365 status, while N-sight, RMM, and ScreenConnect join the
  existing aggregate `rmm` status exposed by the API.
- Native `<details>` expansion is controlled so search and selected tools auto-expand;
  selection and eight-tool disabling remain in the existing screen callback.
- No auth, authorization, payload, server limit, approval, migration, or data-boundary
  logic changed.

## Version & Compatibility Evidence

- No version or API changes. The implementation uses the existing React/Vite/TypeScript
  stack and the existing `DashboardContext.connectors` and `/tools` response shapes.
- `npm ci --ignore-scripts` and `npm ls --depth=0` verified the committed lockfile
  installation: React/React DOM 19.2.8, Vite 8.2.2, Vitest 4.1.11, TypeScript 7.0.2,
  lucide-react 1.33.0, and React Router 7.18.2 among the direct packages.
- A network `npm outdated --json` probe did not return before it was interrupted; no
  upgrade was applied because this task does not change dependency ranges or APIs.
- Remaining compatibility risk is limited to the existing Vite config-loader and chunk
  size warnings reported during validation.

## Open Questions

- None.

## Test Results

- Agents suite: 20 passed.
- Full UI suite, run 1: 59 files / 298 tests passed.
- Production build: passed.
- Full UI suite, run 2: 59 files / 298 tests passed.
- `git diff --check`: passed.

## Diff Summary

- Added a reusable Agents picker with prefix-based groups, native collapsible sections,
  name/title/description search, live group and field counters, approval/risk badges,
  and non-blocking connector configuration warnings.
- Extended Agents tests for grouping, title search, auto-expansion, counts, risk badges,
  and connector warning rendering.
- Existing agent payload and downstream selected-tool controls remain intact.

## Requested Review Focus

- narrow diff review
- confirm connector aliases and default collapsed/selected/search expansion behavior
- confirm no agent payload or approval semantics changed
