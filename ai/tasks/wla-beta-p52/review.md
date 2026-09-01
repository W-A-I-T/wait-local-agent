# Review

## Changed Files

- `ui/src/api/client.ts`
- `ui/src/screens/Consultant.tsx`
- `ui/tests/api-client.test.ts`
- `ui/src/screens/Consultant.test.tsx`
- `ai/tasks/wla-beta-p52/{implementation.md,review.md,status.json}`

## Risk Areas

- The client-scope matcher intentionally uses backend wording substrings so
  endpoint-specific variants remain actionable; future wording changes need a
  corresponding UI test/update.
- Structured capability details are retained as parsed error detail for the
  Consultant gate, while unknown 403 bodies remain generic and retryable.
- No secrets, authorization decisions, data boundaries, or outbound API
  requests were changed.

## Version & Compatibility Evidence

No dependency or API version changes. `npm ci --ignore-scripts` installed the
existing lockfile successfully; `npm ls --depth=0` confirmed the declared
compatible versions, including Vite 8.2.2, Vitest 4.1.11, TypeScript 7.0.2,
React 19.2.8, and React Router 7.18.2. The production build passed against
those versions. `npm audit` could not reach the registry due unavailable DNS,
so live advisory verification remains a follow-up.

## Open Questions

- No implementation questions remain. Claude/human review is pending.

## Test Results

- Focused: 2 files, 25 tests passed.
- Full UI suite: 69 files, 370 tests passed, twice.
- Production build: passed; existing Vite config-loader and large-chunk
  warnings only.
- `git diff --check`: passed.

## Diff Summary

- API errors now retain parsed detail and classify known client-scope failures
  as an actionable client-selection message across relevant statuses.
- Consultant pack language is restricted to structured
  `capability_required` responses; tenant-scope 403s show retryable client
  selection guidance.
- Regression coverage covers all verified wording variants, generic 403s, the
  structured capability path, and Consultant rendering.

## Requested Review Focus

- Narrow diff review; confirm no non-UI files or retry/state-machine behavior
  changed.
