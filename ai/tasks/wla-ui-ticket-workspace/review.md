# Review: unified ticket workspace

Scope check:

- Changes are limited to `ui/src/screens/Tickets.tsx`,
  `ui/src/api/types.ts`, the new screen test, `CHANGELOG.md`, and these task
  documents.
- No backend, routes, sidebar, `src/wait_local_agent/`, or `tests/` files were
  changed.

Review notes:

- The list request includes `client_id` only when the app-shell client selector
  has a value; the unfiltered request remains available for appliance scope.
- Ticket IDs are URL-encoded for all detail and action requests.
- Context 404s are treated as an expected no-graph state rather than an alert
  or render failure.
- Existing write controls remain disabled for read-only users and existing
  approval-gated endpoints are unchanged.
- Provider-specific terminology is retained only inside the preserved sync
  action; the primary navigation and workspace copy are provider-neutral.

Remaining gate: Claude should run the seeded browser verification and final
review before merge.
