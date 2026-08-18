# Implementation

- Added admin-only company discovery to `ConnectorInstances.tsx` for HaloPSA
  and ConnectWise, including paginated provider requests, safe response
  parsing, company selection, and the required manual-entry fallback note.
- Added the external-company to WAIT-client mapping form with quarantine
  exclusion, JSON POST creation, mapping refresh, and success/error notices.
- Added admin Verify actions for unverified mappings and verified
  `StatusChip` rendering after refresh.
- Extended `ConnectorInstances.test.tsx` for empty discovery, Halo mapping
  creation, ConnectWise discovery, unsupported-provider hiding, and verify.
- Updated `CHANGELOG.md`.

Validation passed:

- Focused: `ConnectorInstances.test.tsx` — 12 tests.
- Full: `npm test -- --run` — 48 test files, 229 tests passed in 9.37s.
- Build: `npm run build` — 1871 modules transformed; built in 2.12s.
- Build emitted the existing warning for a minified chunk larger than 500 kB.
