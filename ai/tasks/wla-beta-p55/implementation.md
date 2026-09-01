# Implementation Notes

## Summary

- Wired scoped write actions to `useDashboard().selectedClientId` across Playbooks, Workflow Designer, Scheduled Jobs, Knowledge ingest, Technician Chat, Agents, and Consultant.
- Reused `ClientIdSelect` for scheduled playbook/report creation, Knowledge ingest, and Technician Chat. The selector updates the existing top-bar selection; no second scope source was added.
- Added explicit no-client gates for scoped actions. Scheduled playbook/report params now merge the selected client ID as the source of truth, overwriting any freeform `params.client_id`.
- Agents keeps an existing agent's stored `client_id` while defaulting/synchronizing the blank form from the top-bar selection. Consultant preserves blueprint/local precedence, then falls back to the auth scope, top-bar selection, discovery scope, and first blueprint scope.

## Contract Drift and Scope Decision

- The plan's line references had shifted, but all named files and actions were present.
- Consultant already had a `resolveClientId` helper parameter named `selectedClientId`; its callers were passing the selected blueprint client instead. The fix passes the real top-bar selection after the authenticated scope and adds it to `currentClientId()` and discovery-field fallback resolution.
- Backend verification of `src/wait_local_agent/api/app.py` confirmed `/knowledge/ingest` rejects an unresolved scope with `403 knowledge ingestion requires a client scope` (lines 6620-6638). Knowledge ingest is therefore required and sends `client_id`.
- Backend verification also confirmed workflow gallery create/update, technician chat session creation, scheduled playbook creation, and scheduled report creation already accept/require client scope. No backend changes were needed.

## Commands Run

- `npm ci` — installed the committed lockfile tree; audit reported 0 vulnerabilities.
- `npm ls --depth=0` — resolved the declared tree, including Vite `8.2.2`, Vitest `4.1.11`, React `19.2.8`, TypeScript `7.0.2`, and Playwright `1.62.1`.
- `npm outdated --json` — no outdated compatible dependency results.
- Focused Vitest acceptance set — 5 files, 33 tests passed.
- `npm test -- --run` — 71 files, 397 tests passed; run twice.
- `npm run build` — passed (`tsc -b` and Vite production build).
- `git diff --check` — passed.

## Files Touched

- Production: `ui/src/screens/Agents.tsx`, `Consultant.tsx`, `Knowledge.tsx`, `Playbooks.tsx`, `ScheduledJobs.tsx`, `TechnicianChat.tsx`, and `WorkflowDesigner.tsx`.
- Tests: corresponding screen tests plus `ui/src/screens/ClientIdSelectScreens.test.tsx` and `ui/tests/wla04-surfaces.test.tsx`.
- Task artifacts: `implementation.md`, `review.md`, and `status.json`.

## Follow-Up

- No code follow-up is required. Human review/merge remains the next action.
