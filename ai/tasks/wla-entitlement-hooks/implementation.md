# Implementation Notes

## Summary

- Added the neutral public-runtime entitlement hooks from the plan:
  - Strict offline Ed25519 license-v2 verification with pinned-key rotation support and `WAIT_LICENSE_PUBKEYS` configuration.
  - Pack-loader ladder: commercial `pack_enabled_v2`, legacy HMAC `pack_enabled`, then locked/false; the public runtime never interprets `max_managed_clients`.
  - Viewer-accessible `GET /entitlement`, returning the loaded commercial pack's declared status or `{"commercial": null}`.
  - Migration 12 `commercial_activations` bookkeeping with tenant-scoped, idempotent store CRUD and audited MSP-admin/operator routes; activation has no public-runtime behavior effect.
  - Conditional MSP-admin Clients UI controls and neutral managed/unmanaged status chip, shown only when commercial entitlement is present.
  - Surface coverage, legal-policy documentation, migration pin updates, and focused backend/UI tests.
- Preserved Community behavior: no public count, limit, gate, degradation, or nag logic was added.

## Commands Run

- `pwd`, `git remote -v`, and `git status --short --branch`: confirmed W-A-I-T/wait-local-agent and the requested branch; pre-existing worker lock metadata was preserved.
- `/usr/bin/python3 -m compileall -q src tests`, JSON parsing, and `git diff --check`: passed.
- `/home/josephp/.local/bin/ruff check src tests`: passed.
- Repository venv mypy over the changed Python sources: passed with no issues.
- Alternate available venv Bandit scan over changed Python sources: exit 0; output contained existing baseline nosec/deprecation warnings only.
- UI `npm exec -- vitest run src/screens/ClientsEntitlement.test.tsx`: 1 test passed.
- UI `npm run build`: passed with existing Vite native-config and large-chunk warnings.
- Pure license/store and loader/entitlement smoke checks: passed without pytest.
- Full pytest and Playwright were intentionally not run per the task contract. Direct API `create_app` smoke was not usable in the available environments: one lacked `itsdangerous`, while the complete alternate environment did not return within the diagnostic timeout.

## Files Touched

- `.env.example`
- `ai/tasks/wla-entitlement-hooks/{implementation.md,review.md,status.json}`
- `docs/ai-workflow/surface-coverage.json`
- `docs/legal/community-vs-commercial-use.md`
- `src/wait_local_agent/{config.py,license_v2.py,models.py,store.py}`
- `src/wait_local_agent/api/{app.py,packs/loader.py}`
- `tests/{test_entitlement_hooks.py,test_license_v2.py,test_principals.py,test_spine_p0.py,test_wla_a_pr3b_poll_lease.py,test_wla_p1_clients.py}`
- `ui/src/api/types.ts`, `ui/src/app/DashboardContext.tsx`, `ui/src/screens/Clients.tsx`, `ui/src/screens/ClientsEntitlement.test.tsx`

## Follow-Up

- Claude cross-family review remains required by the task metadata, followed by human merge authority.
- No PR, commit, or push was created, as required by the plan.
- The existing environment has dependency drift (`cryptography` 48.0.1 in one venv versus the repository's declared minimum, and pre-existing invalid UI package installs); no dependency change was needed for this task.

- 2026-09-01T20:15:59Z: Launching Codex gpt-5.6-luna implementation through the artifact runtime in /home/josephp/wait-local-agent-main.

- 2026-09-01T20:38:27Z: Codex gpt-5.6-luna completed successfully; repository verification is next.
