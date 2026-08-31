# Implementation Notes

## Summary

- Added a shared `AutomationsShell` around the five existing automation routes.
  It provides the `Automations` heading, active-surface subtitle, five stable
  route tabs, and the contract descriptions without changing screen data or
  execution logic.
- Renamed the Control sidebar entry from `Workflows` to `Automations` while
  keeping `/workflows` unchanged.
- Removed `Workflow Designer` from Workspace and `Playbooks`, `Smart Actions`,
  and `Templates` from System / Advanced. Those routes remain available from
  the shell tabs.
- Added the requested Workflows, Workflow Designer, and Playbooks cross-links.
- Updated the shell/sidebar tests and the existing Smart Action catalog test
  that asserted the old sidebar destination.

### Tab descriptions

- Run: `Start a reviewed workflow template against a ticket. Templates are code-reviewed and cannot be edited here.`
- Playbooks: `Multi-step service workflows from the library. Publish a tenant copy to enable, preview, and run it.`
- My templates: `Tenant-editable copies of workflow templates: rename, describe, enable, import/export, revisions.`
- Designer: `Draw a design graph for a template copy. Designs are saved and versioned but do not change what runs yet.`
- Action catalog: `Every bounded action agents and workflows can use, with risk and approval requirements.`

## Commands Run

- `npm ci --ignore-scripts` — installed the committed `ui/package-lock.json`; audit reported 0 vulnerabilities.
- `cd ui && npm test -- --run src/app/__tests__/AutomationsShell.test.tsx src/app/__tests__/Sidebar.test.tsx` — 2 files, 14 tests passed.
- `cd ui && npm test -- --run` — 60 files, 303 tests passed.
- `cd ui && npm test -- --run` — repeated per contract; 60 files, 303 tests passed.
- `cd ui && npm run build` — TypeScript and Vite production build passed.
- `git diff --check` — passed.

The Vite commands emit the existing config-loader extension warning and a
large-main-chunk warning; neither is caused by this UI-only change.

## Files Touched

- `ui/src/app/AutomationsShell.tsx`
- `ui/src/app/__tests__/AutomationsShell.test.tsx`
- `ui/src/app/Sidebar.tsx`
- `ui/src/app/__tests__/Sidebar.test.tsx`
- `ui/src/routes.tsx`
- `ui/src/screens/Playbooks.tsx`
- `ui/src/screens/WorkflowDesigner.tsx`
- `ui/src/screens/Workflows.tsx`
- `ui/src/styles.css`
- `ui/tests/SmartActionCatalog.test.tsx`

## Follow-Up

- No follow-up is required for the planned scope. Existing Vite warnings remain
  for a separate tooling cleanup.
