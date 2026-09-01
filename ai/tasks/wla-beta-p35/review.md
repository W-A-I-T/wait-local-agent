# Review

## Changed Files

- `ui/src/screens/Workflows.tsx`
- `ui/src/screens/Playbooks.tsx`
- `ui/src/components/SchemaForm.tsx`
- `ui/src/lib/structured-inputs.ts`
- `ui/src/components/__tests__/SchemaForm.test.tsx`
- `ui/tests/Workflows.test.tsx`
- `ui/tests/Playbooks.test.tsx`
- `ui/e2e/production-readiness.spec.ts`
- Task records: `implementation.md`, `review.md`, `status.json`

## Risk Areas

- Field controls infer primitive types/options from backend descriptions because
  the current API exposes descriptive strings rather than typed JSON Schema;
  ambiguous values intentionally retain JSON editing.
- Playbook required inputs are aggregated across steps, so one missing value
  blocks preview/run before any request is sent; published entry definitions
  are used consistently for rendering and validation.
- Raw JSON remains object-only, is kept synchronized with the structured value,
  and invalid drafts are blocked client-side, including arrays and primitives;
  no backend validation semantics or request envelope changed.
- Secret redaction in `SchemaForm` remains active when the raw editor syncs.

## Version & Compatibility Evidence

- No version or API changes. The existing `ui/package-lock.json` remains
  unchanged; `npm ls --depth=0` resolves the existing compatible stack,
  including Vite 8.2.2, React 19.2.8, TypeScript 7.0.2, and Vitest 4.1.11.
  The implementation consumes the existing `/workflows/templates` and
  `/msp/playbooks` response shapes.

## Open Questions

- None.

## Test Results

- Focused UI tests: 3 files, 19 tests passed.
- Full UI suite: 63 files, 334 tests passed on both required runs.
- Production UI build: passed (`tsc -b && vite build`).
- Existing-lock install/audit: `npm ci --ignore-scripts` recorded 0
  vulnerabilities; current validation confirmed the lockfile-installed tree.
- Existing warnings: Vite native-config compatibility warning and large
  minified chunk advisory; neither is introduced by this task.

## Diff Summary

- Workflow and playbook launchers now present declared inputs as labeled
  controls, aggregate playbook step requirements, validate required fields
  inline, and retain a Raw JSON (advanced) two-way fallback. Templates and
  playbooks without declarations show the no-additional-fields state. Raw
  JSON arrays/primitives are rejected before request creation, and customized
  published playbook requirements are validated from the published definition.

## Requested Review Focus

- Confirm metadata-to-control inference, request-body equivalence, required
  validation, raw JSON synchronization/redaction, and preservation of the
  existing endpoint/auth boundaries. Also confirm the two recovery regressions
  covered by the added tests.

## Historical Blocker

- 2026-08-31T04:35:14Z: Codex implementation exited with status 127.

## Resolution

- 2026-08-31T04:39:49Z: Recovered the committed implementation, fixed the
  object-validation and published-definition consistency gaps, and completed
  focused tests, both required full-suite runs, the production build, and the
  installed dependency-tree check. Ready for the required cross-family review.

## Handoff Constraint

- 2026-08-31T04:42:04Z: Commit/push could not be completed because the
  worktree Git index at `/home/josephp/wait-local-agent/.git/worktrees/wla-beta-p35/index.lock`
  is outside the writable sandbox and read-only. Existing PR #477 remains
  open at the prior committed implementation; commit and push the current
  working-tree fixes before review.
- The required live PR metadata query was attempted but `api.github.com` was
  unreachable from this sandbox, so current CI state could not be confirmed.

## Final revision resolution

- Updated only `ui/e2e/production-readiness.spec.ts` for the reviewed CI
  regression: QBR now fills the structured `Period start` and `Period end`
  controls instead of the collapsed raw JSON textarea.
- Scanned the rest of the spec; no other selectors depended on the old
  raw-JSON-first layout.
- `npm run test:e2e -- --list` passed and listed the smoke test. Full browser
  execution was not runnable here because the Playwright config requires an
  externally running UI/API environment at `127.0.0.1:5173`.
- Full unit tests passed twice (63 files, 334 tests each) after the e2e-only
  revision; build and `npm ls --depth=0` also passed.

## Live PR state

- Required query completed: [PR #477](https://github.com/W-A-I-T/wait-local-agent/pull/477)
  is open and currently `UNSTABLE` because the already-pushed
  `compose-browser` check is failing; backend, backend-windows, UI,
  desktop-pr, and gitleaks checks are successful.
- The local e2e selector fix is uncommitted in this sandbox, so the live PR
  state does not yet include it.

## Dependency freshness note

- No dependency or API changes were made; `ui/package-lock.json` is unchanged.
  The installed tree resolves Vite 8.2.2, React 19.2.8, TypeScript 7.0.2,
  Vitest 4.1.11, and Playwright 1.62.1. `npm outdated --json` did not return
  within the restricted environment, so no live registry freshness claim is
  made.

## Claude review — CI regression on PR #477 (revision requested)

The compose-browser CI job fails: `ui/e2e/production-readiness.spec.ts:75`
fills `getByLabel("Input JSON for Quarterly Business Review")`, which is no
longer reachable — this packet collapsed raw JSON under the "Advanced"
expander and QBR's required inputs now render as structured fields.

Fix the e2e spec (spec ONLY — do not change the shipped UI):
1. Update the QBR interaction to the new UI: fill the structured required
   fields (period_start / period_end) directly, OR expand the Advanced
   section first and use the current raw-JSON label. Prefer the structured
   path — it exercises the new UX.
2. Check the rest of the spec for other selectors that assumed the old
   raw-JSON-first layout (Workflows launcher "Template payload JSON" etc.)
   and update the same way.
3. If the Playwright environment isn't runnable in your session, say so and
   Claude will rely on CI. Run `cd ui && npm test -- --run` once to confirm
   no unit-test impact.

## Claude note — resuming interrupted CI-fix round

Your previous run was interrupted after two small UI fixes (published-definition
required-inputs derivation in Playbooks.tsx and an onJsonValidityChange call in
SchemaForm.tsx) but BEFORE updating ui/e2e/production-readiness.spec.ts. Those
two UI fixes are accepted — keep them. Now finish the round: update the e2e
spec's QBR interaction (and any other stale raw-JSON-first selectors) to the
structured-fields UI per the earlier review entry, then run
`cd ui && npm test -- --run` and record results.
