# Implementation — `wla-ui-clients-mutations`

Implemented the Clients screen lifecycle and connector mapping actions within
the requested UI-only boundary.

## Scope

- Added client detail loading from `GET /clients/{id}` and filtered connector
  mapping display from `GET /client-connector-mappings`.
- Added administrator-gated create (`POST /clients`) and status edit
  (`PATCH /clients/{id}`) forms with required-field validation, inline errors,
  success feedback, and list refreshes.
- Added administrator-gated verification for unverified mappings using
  `POST /client-connector-mappings/{id}/verify`, with busy and inline error
  states.
- Widened `Client` to the verified detail response shape and retained the
  list-specific `ClientDirectoryEntry` type.
- Added focused Vitest coverage for detail, create, edit, verify, and existing
  loading/error behavior.

No files under `src/`, `tests/`, `ui/src/app/`, or `ui/src/routes.tsx` were
changed. No commit or push was performed.

## Security and scope review

- Viewer-readable detail and mapping requests remain available to the screen;
  all mutating controls are hidden unless the resolved role is `admin`.
- Client and mapping IDs are URI-encoded. Form payloads contain only the
  backend contract fields and no credentials or secret values.
- The reserved `__quarantine__` client remains excluded from the directory.
