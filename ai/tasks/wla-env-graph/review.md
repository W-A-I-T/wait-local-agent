# Review

## Changed Files

- Backend graph storage/service/API/scheduler: `src/wait_local_agent/{models.py,store.py,operational_graph.py,scheduler.py}` and `src/wait_local_agent/api/app.py`.
- UI and tests: `ui/src/api/types.ts`, `ui/src/screens/Clients.tsx`, `ui/src/screens/ScheduledJobs.tsx`, `ui/src/screens/Schedules.tsx`, `ui/src/screens/__tests__/Clients.test.tsx`, `tests/test_wla_f1_operational_graph.py`, and `tests/test_scheduler.py`.
- Documentation and task state: `docs/ai-workflow/surface-coverage.json`, `docs/concepts/operational-graph.md`, `implementation.md`, `review.md`, and `status.json`.

## Risk Areas

- Microsoft 365 reads are client-scoped through the existing profile resolver and are gated by the MSP/operator role and probing setting. Persisted graph attributes are operational metadata only; tokens, message content, and credentials are not stored.
- Ticket and collector graph hooks run after their source persistence and use idempotent upserts. The collector hook is client-scoped from persisted asset ownership.
- Entity and relationship pages are independently bounded to 200 rows, with SQL totals and `has_more`; concurrent writes can still change totals between requests, as expected for a live graph.
- `graph_sync` schedules accept exactly one client target, reject conflicting target fields, re-check active-client/probing/RMM conditions at execution, and audit success/failure without recording returned secrets.
- The UI preserves read-only graph behavior and marks records older than seven days as stale rather than hiding them.

## Version & Compatibility Evidence

- No dependency versions changed. Existing compatible pins remain `msgraph-sdk==1.61.0`, `APScheduler==3.11.3`, `httpx==0.28.1`, FastAPI `>=0.139,<1`, and `slowapi>=0.1.10,<0.2`; the UI lockfile resolves Vite 8.2.2 and Vitest 4.1.11.
- The implementation uses the existing Microsoft Graph v1.0 users and Intune managed-device surfaces and their existing client fields; current official references are linked in the handoff response. No API version migration was introduced.
- UI build/tests passed on the repository's current Node-compatible toolchain. Remaining environment risk is the missing local `slowapi`/`bandit` tooling and Microsoft tenant permission/licensing configuration, not an unvalidated package upgrade.

## Open Questions

- None for the plan contract. The next reviewer should confirm tenant-level Graph permissions and the desired production sync cadence before deployment.

## Test Results

- `ruff check src tests` passed.
- Python source compilation passed.
- UI build passed; full Vitest suite passed with 80 files and 458 tests.
- Direct fake-provider graph smoke passed, including idempotency and pagination behavior.
- `mypy src tests` remains environment-blocked by six existing `slowapi` import errors; `bandit -r src` could not start because the command is absent.
- Backend pytest and Playwright were not run per the task plan.

## Diff Summary

- Added graph pagination/filtering and count APIs; automatic ingestion/collector seeding; Microsoft 365 inventory seeding; protected sync endpoint; graph-sync scheduler registration/execution/audit; and Environment UI controls.

## Requested Review Focus

- Verify tenant/client boundaries and no credential/content persistence in the Microsoft 365 path.
- Verify scheduler target validation, probing gates, audit redaction, and route surface coverage.
- Verify graph totals/`has_more` semantics and idempotency under repeated ingestion/collection.
- Verify UI remains bounded and read-only while clearly exposing RMM versus Microsoft 365 sync state.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED after four fix rounds (collector clientless-run FK skip;
filtered-pagination totals contract implemented at SQL level; Annotated Query
params for direct-call tests; audit-hygiene fix — graph_sync failures now
record generic sanitized summaries, never interpolated provider error bodies).

Scope audit clean. Security: M365 seeding is metadata-only through the #510
resolution seam; all new writes fail-closed on client scope; sync-m365 gated
(admin + msp-operator + probing); scheduler graph_sync kind validated against
arbitrary targets; no secrets in graph refs or audit detail (test-enforced).

Live validation (branch build, port 18795): paged graph endpoint returns the
honest contract ({refs, links, total_refs, total_links, has_more,
entity_type_counts}) with filters applied. Noted during live test: deep-linking
top-level UI paths that collide with API GET routes (/clients etc.) returns
API JSON — PRE-EXISTING appliance limitation from the PR-1 SPA design (dev
proxy masks it); filed as a separate follow-up task rather than scope-creeping
this PR. In-app navigation unaffected (E2E passes from /).

Test evidence: full suite 95.02% vs 95% gate; mypy clean (314 files); bandit
0; UI 458/458 with build; operational_graph.py at 100%.
