# Review — wla-ui-connector-browse-autotask

## Scope and safety

The change is UI-only and limited to the reusable browse component, its tests,
the additive Autotask section, the changelog, and this task documentation. The
component issues only GET requests through the existing `apiFetch` helper. It
does not expose write, action, execute, POST, or PATCH controls. Provider field
names are not hardcoded; columns come from returned item keys.

## Validation

From `ui/`:

- `npm test -- --run`: passed — 43 test files, 181 tests.
- `npm run build`: passed — Vite production build completed successfully.
- Build emitted the existing non-failing warning that a JavaScript chunk is
  larger than 500 kB after minification.

The requested browser verification and final Claude gate remain pending.
