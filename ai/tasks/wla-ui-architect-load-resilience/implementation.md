# Implementation

- Updated only the `refresh()` callback in `ui/src/screens/Consultant.tsx` to
  load blueprints, use cases, monitoring, and discovery sessions with typed
  `Promise.allSettled` results.
- Each fulfilled section updates its own state. Failed sections remain
  isolated, while blueprint selection and architecture derivation use an empty
  row set when the blueprint request fails.
- Replaced the blanking load error with a scoped notice listing only failed
  sections; successful refreshes clear the notice. The existing loading
  cleanup remains in `finally`.
- Extended the Consultant Vitest coverage for a discovery-sessions rejection
  while the blueprint request succeeds.

## Validation

- `npm test -- --run`: passed; 48 test files and 215 tests passed. Start
  23:56:15; duration 10.30s (transform 6.86s, setup 6.00s, import 16.67s,
  tests 56.61s, environment 54.37s).
- `npm run build`: passed; 1,871 modules transformed, emitted a 580.82 kB
  JavaScript bundle, and completed in 2.08s. Existing chunk-size warning was
  reported for chunks larger than 500 kB.
