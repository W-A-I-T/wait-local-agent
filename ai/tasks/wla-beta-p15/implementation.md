# Implementation Notes

## Summary

- Added shared, accessible `LoadingState` and `EmptyState` components and applied them across the empty-state sweep.
- Preserved existing fetches, request shapes, role gates, and backend contracts. Loading flags represent the initial response so refreshes do not erase active form input.
- Added actionable empty-state copy, including the disabled demo-seed command for Clients and Tickets.
- Kept setup progress visible in the sidebar as `Setup: N of 4`, linked to `/?onboarding=1`, regardless of the Overview wizard dismissal state.
- Replaced the Microsoft Admin Access fresh-install dead-select experience with an explanation of where principals come from and what to configure next.

## Screen Coverage

| Screen | Loading state | Empty state / next step |
|---|---|---|
| Agents | Agent definitions and tool catalog | Create your first agent below |
| Approvals | Approval requests | Explain governed-action review |
| Audit | Audit events | Explain that events follow recorded actions |
| Backfills | Backfills | Preview a backfill above |
| Collectors | Catalog and runs | Choose a collector above |
| EndUserSupport | Request lookup | Check a request |
| Executions | History and details | Explain when execution history appears |
| M365Actions | Administrator-access check | Role-gated; no empty list |
| MicrosoftAdminAccess | Principals/clients and grants | Configure a technician identity or eligible client |
| ScheduledJobs | Scheduled jobs | Create a schedule above; explain scheduled+enabled agent requirement |
| Templates | Local templates | Create a local template above |
| WorkflowDesigner | Workflow designs | Create a local design from a reviewed template |
| Workflows | Templates and runs | Start a workflow above |
| Clients | Client directory | Evaluation-only demo seed command, writes disabled |
| Tickets | Ticket list | Evaluation-only demo seed command, writes disabled |

## Commands Run

- `npm ci` (from `ui/`) — installed the existing lockfile; 141 packages added, audit found 0 vulnerabilities. No dependency files changed.
- `npm outdated --json` (from `ui/`) — no outdated packages reported.
- `npm test -- --run` (from `ui/`) — green: 58/58 test files, 282/282 tests. Final validation run 1.
- `npm test -- --run` (from `ui/`) — green: 58/58 test files, 282/282 tests. Final validation run 2.
- `npm run build` (from `ui/`) — passed (`tsc -b` and Vite production build). Existing warnings remain for the Vite config extension and a >500 kB bundle chunk.
- `git diff --check` — passed.

## Files Touched

- `ui/src/components/LoadingState.tsx`, `ui/src/components/LoadingState.test.tsx`
- `ui/src/components/EmptyState.tsx`, `ui/src/components/EmptyState.test.tsx`
- `ui/src/styles.css`
- `ui/src/app/Sidebar.tsx`, `ui/src/app/__tests__/Sidebar.test.tsx`
- `ui/src/screens/Agents.tsx`, `Approvals.tsx`, `Audit.tsx`, `Backfills.tsx`, `Clients.tsx`, `Collectors.tsx`, `EndUserSupport.tsx`, `Executions.tsx`, `M365Actions.tsx`, `MicrosoftAdminAccess.tsx`, `ScheduledJobs.tsx`, `Templates.tsx`, `Tickets.tsx`, `WorkflowDesigner.tsx`, `Workflows.tsx`
- `ui/src/screens/__tests__/Approvals.test.tsx`, `ui/src/screens/M365Actions.test.tsx`, `ui/src/screens/MicrosoftAdminAccess.test.tsx`
- `ui/tests/Agents.test.tsx`, `ui/tests/Templates.test.tsx`, `ui/tests/WorkflowDesigner.test.tsx`
- `ai/tasks/wla-beta-p15/implementation.md`, `review.md`, `status.json`

## Follow-Up

- Human/Claude review and normal merge authority remain outstanding; no PR was created by this implementation run.
- The existing Vite config-loader and bundle-size warnings are unrelated to this UI sweep.
