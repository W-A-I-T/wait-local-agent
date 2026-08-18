# Review

## Scope

The change is limited to the UI dev-proxy route list, its existing unit test,
the changelog, and this task documentation. Backend paths were not modified.

## Validation

- `npm test -- --run`: passed (40 files, 170 tests)
- `npm run build`: passed (Vite production build; emitted existing chunk-size warning)

## Security and edge cases

`/clients` follows the existing proxy prefix convention and therefore covers
both the collection endpoint and client detail paths. No authentication,
backend, data-boundary, or production API-base behavior was changed.
