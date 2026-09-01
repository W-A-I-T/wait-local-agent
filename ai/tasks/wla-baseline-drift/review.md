# Review

## Changed Files

- Backend baseline model, migration/CRUD, composition/diff engine, Microsoft summary projection, API routes, and scheduler: `src/wait_local_agent/{baseline.py,models.py,store.py,scheduler.py,api/app.py}` and `src/packs/microsoft_admin/{insights.py,core.py}`.
- Tests and migration pins: `tests/test_baseline.py`, the six applicable existing migration-pin files, and `ui/src/screens/__tests__/Clients.test.tsx`.
- UI, documentation, route manifest, and task artifacts: `ui/src/{api/types.ts,screens/Clients.tsx}`, `docs/ai-workflow/surface-coverage.json`, `docs/concepts/baseline-drift.md`, and `ai/tasks/wla-baseline-drift/*`.

## Risk Areas

- Source readiness is carried into every snapshot; counters from non-ready Microsoft sources are excluded rather than recorded as healthy zeroes, and either-side unavailable sections produce `verification_unavailable`.
- Drift polarity is explicit only for declared numeric posture counters. Canonical mapping/list ordering is normalized before hashing and comparison.
- Approval correlation is same-client, approved, executed-window, keyword-based evidence and is phrased as expected change or no matching approved change; it never asserts unauthorized change.
- All baseline routes resolve client scope before reads/writes; writes require admin MSP-operator access, write enablement, and non-demo mode. Drift requires live read probing.
- Scheduler targets are restricted to one client, and failures record only exception type plus a generic provider-failure message.
- Persisted baseline JSON is passed through the existing redaction path and contains normalized counters, IDs, counts, statuses, and timestamps rather than raw provider payloads or credentials.

## Version & Compatibility Evidence

- No new dependencies or dependency versions were introduced. Existing FastAPI, APScheduler, Microsoft Graph SDK, React, TypeScript, and Vite pins remain in use.
- The Microsoft posture change is an internal reusable summary projection over the existing Graph-backed dashboard; live dashboard behavior and provider API versions are unchanged.
- The current UI lockfile was checked offline with `npm --prefix ui install --package-lock-only --ignore-scripts --offline` and remained current. `uv lock --check` could not complete because the machine's global uv cache is read-only; no lockfile changed.
- Remaining compatibility risk is limited to the unavailable full dependency environment and the existing tenant permissions/configuration for live provider probing.

## Open Questions

- None for implementation. Cross-family review should confirm production Graph permissions and the desired baseline snapshot cadence.

## Test Results

- Ruff and TypeScript project compilation passed.
- Focused Clients UI test passed: 1 file, 12 tests.
- Targeted mypy for changed Python modules/tests passed; full `mypy src tests` exposed only two pre-existing unused-ignore findings outside this task.
- Python compilation and `git diff --check` passed.
- Focused backend and UI tests were added but not executed because the plan explicitly prohibits pytest and Playwright; UI type compilation was run.
- Bandit was unavailable, and uv lock verification was environment-limited as documented above.

## Diff Summary

- Added persistent, tenant-scoped client baselines and atomic acceptance; normalized snapshot sections; drift classifications and approved-change labels; guarded API/scheduler integrations; migration pins; documentation; and Baseline UI coverage.

## Requested Review Focus

- Verify unavailable-source handling never becomes healthy-zero drift.
- Verify polarity and ordering-insensitive comparison, approval scope/correlation wording, tenant boundaries, scheduler audit sanitization, and unchanged live-dashboard behavior.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED pending CI coverage confirmation.

Gate rounds: acceptance-matrix build-out enforced (initial delivery had only 5
tests; the full matrix — lifecycle/accept atomicity, unavailable-never-zero,
drift classifications incl. ordering-insensitivity, correlation isolation,
route auth/demo/probing gating, scheduler hygiene, tenant isolation — now
exists and passes); diff engine fixed to recurse into ID-keyed entity maps;
scheduler failure test corrected twice (constructor-injected runner seam;
audit-event selection under shared store).

This PR's modules under the full suite: baseline.py 100%, insights.py 100%,
core.py 100%, scheduler.py ~99%. Local TOTAL reads 94.96% but local
measurement at this margin has proven unreliable vs CI in both directions;
CI's backend job is the authoritative gate and any shortfall will be topped
up against CI's own report.

Security: no provider text in audit detail (test-enforced); correlation
phrasing never claims proof; unavailable sources excluded from drift and
marked verification_unavailable; all routes admin+msp-operator gated,
demo-refused, audited; insights refactor left live-dashboard behavior
unchanged (existing tests unmodified).
