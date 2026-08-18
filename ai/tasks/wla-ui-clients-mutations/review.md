# Review — `wla-ui-clients-mutations`

## Review result

Pending final gate.

- The diff is limited to the Clients screen, API types, focused UI tests,
  changelog, and this task's implementation/status documents.
- Backend contracts were verified before implementation: detail includes
  `client_id`, `name`, `status`, `created_at`, and `updated_at`; PATCH changes
  status; mapping verification returns `retenanted_count`.
- Loading, empty, error, success, and mutation-busy states are represented in
  the screen markup.

## Validation

- `cd ui && npm test -- --run`: 38 test files passed, 166 tests passed.
- `cd ui && npm run build`: passed; Vite emitted only its existing warning about
  a JavaScript chunk larger than 500 kB.
