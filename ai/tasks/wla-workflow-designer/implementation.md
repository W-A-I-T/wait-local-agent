# Workflow Designer implementation

## Scope

- Added a validated `wait-local-agent.workflow-design` graph format.
- Stored graph definitions with gallery entries and revisions.
- Added default trigger/action/approval/end projections from reviewed templates.
- Added a React canvas, node editor, bounded palette, and connection editor.
- Added navigation at `/workflow-designer`.

## Existing primitives used

- `template_gallery_entries` and `template_gallery_revisions` in SQLite.
- Existing tenant-scoped gallery GET/POST/PATCH routes and technician/viewer RBAC.
- Existing `apiFetch`, DashboardContext write gating, gallery template catalog, and revision UX.

## Explicit non-goals

The graph is an artifact only. This slice does not bind nodes to runtime
execution, call external providers, publish to Power Platform, or activate
autonomous operation.
