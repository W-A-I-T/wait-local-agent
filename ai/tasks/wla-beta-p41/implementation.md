# Implementation Notes

## Summary

- Implemented all six UI dead-end fixes from `plan.md`.
- Connector Instances now loads GET-backed detail, edits only changed non-secret PATCH fields, supports active/inactive/disabled status changes, and shows 409 conflicts inline.
- Playbook subscriptions now have inline GET/PATCH editing for the backend-supported `input_mapping` and `enabled` fields; event type and playbook binding remain read-only because the PATCH model forbids them.
- Scheduled Jobs now supports `playbook_id` creation and renders playbook targets in list/detail views.
- MCP now POSTs JSON-RPC `initialize`, renders `result`, and labels the static fallback honestly when the live handshake fails.
- Audit CSV/JSON exports now use `/audit-events/export` with `format`, `from`, `to`, and optional `client_id` parameters.
- Tickets now exposes a ConnectWise draft provider path using the verified `action_type`/`fields` payload.

## Commands Run

- `npm ci` — installed the lockfile toolchain; audit reported 0 vulnerabilities.
- `npm outdated --json` — no updates reported.
- `npm run build` — passed; pre-existing Vite config/chunk-size warnings remain.
- `npm test -- --run` — passed three times: 65 files, 339 tests on each run.
- Focused affected-suite run — passed: 6 files, 18 tests.
- `git diff --check` — passed.

## Files Touched

- `ui/src/api/types.ts`
- `ui/src/screens/{ConnectorInstances,Playbooks,ScheduledJobs,McpIntegration,Audit,Tickets}.tsx`
- `ui/tests/{ConnectorInstances,McpIntegration,Playbooks,ScheduledJobs,Tickets,Audit}.test.tsx`
- `ai/tasks/wla-beta-p41/{implementation,review}.md` and `status.json`

## Follow-Up

- No implementation follow-up. Human/Claude review remains required before merge.
