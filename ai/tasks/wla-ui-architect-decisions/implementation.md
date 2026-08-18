# Implementation

- Added the typed `ArchitectureDecision` contract and optional architecture
  decision-engine fields to `ui/src/api/types.ts`.
- Added a shape-tolerant Architecture decisions panel to the Solutions
  Architect screen with humanized customer-facing labels, decision summaries,
  rationale, alternatives, status, and requirements.
- Renamed Consultant display copy to Solutions Architect while preserving the
  component, route, file, and export names.
- Added focused Vitest coverage for populated, empty, and oddly-typed decision
  payload behavior.

## Validation

- `npm test -- --run`: passed; 48 test files and 214 tests passed (13.46s).
- `npm run build`: passed; 1,871 modules transformed and production assets
  emitted (2.77s), with the existing chunk-size warning.
