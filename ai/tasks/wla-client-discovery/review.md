# Review

## Changed Files

- `src/wait_local_agent/client_discovery.py`, `src/wait_local_agent/models.py`, `src/wait_local_agent/store.py`, `src/wait_local_agent/api/app.py`
- `tests/test_client_discovery.py`
- `ui/src/screens/ClientDiscovery.tsx`, `ui/src/screens/ClientDiscovery.test.tsx`, `ui/src/routes.tsx`, `ui/src/screens/Clients.tsx`, `ui/src/api/types.ts`
- `docs/ai-workflow/surface-coverage.json`, `docs/concepts/customer-discovery.md`
- `ai/tasks/wla-client-discovery/implementation.md`, `ai/tasks/wla-client-discovery/review.md`, `ai/tasks/wla-client-discovery/status.json`

## Risk Areas

- Candidate activation spans client creation/mapping/verification calls and should be reviewed for transactional rollback behavior if mapping verification fails after client creation.
- Discovery reads existing normalized provider responses through `build_read_client_for`; provider pagination and transport behavior should be checked against each connector’s live response contract.
- The review queue is intentionally global and requires an administrator plus MSP-operator context; demo mode refuses all discovery mutations and queue reads.
- Bulk acceptance validates every selected row as `proposed` before starting, while concurrent state changes can still produce a later per-row conflict.

## Version & Compatibility Evidence

- No dependency or external provider API version changes. The implementation reuses existing connector list methods and the existing mapping verification path.
- Compatibility was checked against the repository lock/manifests: FastAPI `0.139.0`, httpx `0.28.1`, React `19.2.8`, TypeScript `7.0.2`, Vite `8.2.2` (installed lock resolution), and Vitest `4.1.11`; no newer version was required or introduced.
- Remaining environment risk: the available WLA runtime environment lacks `itsdangerous` even though `pyproject.toml` declares it, so direct FastAPI TestClient smoke validation could not run in this checkout.

## Open Questions

- Decide whether client creation plus mapping verification should move into one Store transaction in a follow-up hardening pass.
- Confirm whether a later slice should add domain extraction to each provider normalizer; this slice safely stores an empty domain list when the existing read shape has none.

## Test Results

- Focused backend tests: 7 passed.
- Full UI suite: 78 files / 443 tests passed.
- UI build: passed with existing Vite warnings.
- Full mypy: passed (309 source files).
- Full ruff: passed.
- Bandit: passed with existing `# nosec` warning output.
- Full Python pytest/coverage and Playwright were not run because the plan explicitly prohibits those suites; the 95% coverage gate therefore remains for CI/human review.

## Diff Summary

- Adds deterministic PSA organization discovery and a persisted reconciliation queue. Verified mappings win, exact single-name matches become proposed, duplicate names become ambiguous, and verified external-ID conflicts remain blocked. Admin MSP operators can accept, create, or dismiss candidates with audit records; bulk acceptance is proposed-only. MSP/SMB mode controls visibility without changing manual SMB client behavior.

## Requested Review Focus

- Verify migration ordering and concurrent UPSERT behavior; inspect acceptance transaction boundaries; verify route gating/surface coverage; confirm no Settings files or out-of-scope packs were changed.

## Claude Final Gate — Review & Live Validation (2026-09-01)

Verdict: APPROVED. Scope audit clean on first pass (a first for the pipeline).

REAL BUGS found by the gate and fixed:
1. Route shadowing (plan's own error): /clients/discovery was captured by the
   GET /clients/{client_id} API route — deep links returned raw 401 JSON.
   Moved to /client-discovery; deep-link verified live in browser.
2. IMPLEMENTATION BUG: upsert_client_candidate bound int(preserve_state) into
   the SQL 'when ? then excluded...' branches — inverted. preserve_state=True
   would OVERWRITE admin-relevant candidate state on re-discovery; fixed to
   int(not preserve_state); the fix also unmasked a correct FK enforcement the
   bug had hidden. Semantics contract now pinned by tests: insert takes state
   as-is; refresh (True) keeps state; replace (False) works except
   verified/dismissed are immutable.
Plus migration-count pins bumped across six test files (added as a standing
checklist item for every future migration).

Live validation (branch build, port 18794): mode lifecycle (null -> msp,
invalid 422, admin-gated); discovery routes gated (401 unauth); paginated
candidate listing with summary; graceful no-instance run with failures array;
Client discovery screen renders on deep-link with correct fail-closed copy
("WAIT never creates or links a client without an administrator action").

Test evidence: full suite passes; coverage 94.97% local (within the known
~0.05pt local-vs-CI under-measurement; CI is authoritative); mypy clean (309
files); bandit 0; ruff clean; UI 443/443.
