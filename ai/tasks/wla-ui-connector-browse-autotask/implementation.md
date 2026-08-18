# Implementation — wla-ui-connector-browse-autotask

Implemented the reusable, read-only `ConnectorBrowsePanel` and wired Autotask
as its first consumer on the Connectors screen.

- Health is loaded independently and rendered as a status chip with an optional
  count.
- Tickets and Companies use a segmented tab row and paginated GET requests.
- Table columns are derived from the union of returned item keys, capped at
  eight columns; nested values are JSON-rendered and bounded.
- Loading, empty, API error, and unavailable/not-configured states are rendered
  without assuming an Autotask configuration.
- The component contains no write, POST, PATCH, or execute controls.
- Existing bespoke provider sections were left unchanged.

## Files changed

- `ui/src/components/ConnectorBrowsePanel.tsx`
- `ui/src/components/ConnectorBrowsePanel.test.tsx`
- `ui/src/screens/Connectors.tsx`
- `CHANGELOG.md`
- `ai/tasks/wla-ui-connector-browse-autotask/`

No files under `src/wait_local_agent/` or the repository `tests/` directory
were changed. No commit or push was made.
