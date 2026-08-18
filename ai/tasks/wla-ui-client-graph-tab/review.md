# Review

## Scope and safety

- UI-only change; no backend, migration, `src/wait_local_agent/`, or
  repository-level `tests/` files were changed.
- The graph tab uses only the existing GET graph endpoint and has no sync,
  write, mutation, credential, or secret controls.
- The existing Details content and client/mapping mutation behavior remain
  unchanged beneath the new tab wrapper.
- Graph relationships resolve IDs through a map built from the returned refs;
  unknown IDs fall back to their raw numeric IDs.
- API values are represented with explicit TypeScript types and no `any`.

## Review status

Cross-family review and the final Claude gate remain pending.
