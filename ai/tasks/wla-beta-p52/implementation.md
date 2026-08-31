# Implementation Notes

## Summary

- Added parsed API error detail to `ApiRequestError` without changing the raw
  `technicalDetail` format.
- Added shared client-scope error classification and a consistent actionable
  message for the verified tenant/client-scope variants, including the 400
  scheduled-report variant.
- Consultant sections now use pack-gated copy only when the parsed 403 detail
  has `code === "capability_required"`; plain scope and unrelated 403 errors
  remain retryable error notices.
- No backend files, endpoint contracts, retry behavior, or section state shape
  were changed.

## Backend Contract Verification

Re-verified with `rg` in `src/wait_local_agent/client_scope.py`,
`src/wait_local_agent/api/app.py`, and `src/wait_local_agent/rbac.py` before
finalizing the matcher. The backend currently emits:

- `authenticated principal has no tenant`
- `requested tenant is outside authenticated scope`
- `operation requires a single client scope`
- `client scope is required`
- `chat sessions require a client scope`
- `knowledge ingestion requires a client scope`
- other `requires a client scope` / `requires a tenant scope` variants
- `client_id is required for a scheduled report`

The same search found no `MICROSOFT_ADMIN_CAPABILITY` or `require_capability`
references in `src/wait_local_agent/api/app.py`'s consultant routes. The
structured RBAC shape remains `{detail: {code: "capability_required", ...}}`.

## Commands Run

- `npm ci --ignore-scripts` — completed; 141 packages installed.
- Focused tests: `npm test -- --run tests/api-client.test.ts src/screens/Consultant.test.tsx` — 2 files and 25 tests passed.
- Full UI tests, run 1: `npm test -- --run` — 69 files and 370 tests passed.
- Build: `npm run build` — passed; Vite 8.2.2 transformed 1,881 modules.
- Full UI tests, run 2: `npm test -- --run` — 69 files and 370 tests passed.
- `npm ls --depth=0` — lockfile-installed dependencies are present and satisfy the declared ranges.
- `git diff --check` — passed.
- `npm audit --omit=optional --audit-level=high` could not reach the npm registry because DNS/network access was unavailable; no package or lockfile changes were made.

The test and build runs emitted the existing Vite config-loader warning and
large-chunk warning; neither failed validation.

## Files Touched

- `ui/src/api/client.ts`
- `ui/src/screens/Consultant.tsx`
- `ui/tests/api-client.test.ts`
- `ui/src/screens/Consultant.test.tsx`
- `ai/tasks/wla-beta-p52/{implementation.md,review.md,status.json}`

## Follow-Up

- Claude/human review remains the next task gate.
- Live npm advisory verification should be rerun when registry access is
  available.
