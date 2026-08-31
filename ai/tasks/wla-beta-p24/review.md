# Review

## Changed Files

- `ui/src/lib/connectorSetup.ts`
- `ui/src/screens/Connectors.tsx`
- `ui/src/screens/ConnectorInstances.tsx`
- `ui/src/screens/Settings.tsx`
- `ui/src/styles.css`
- `ui/tests/connectorSetup.test.ts`
- `ui/tests/Connectors.test.tsx`
- `ui/tests/wla-wp17.test.tsx`
- `ui/src/screens/__tests__/ConnectorInstances.test.tsx`
- Task artifacts under `ai/tasks/wla-beta-p24/`

## Risk Areas

- The static setup map must remain synchronized with backend configuration
  names. A focused allowlist test plus direct `rg` verification covers the
  current names; future connector config changes need the map updated.
- The UI reveals a generated credential reference only when instance creation
  partially fails, as required for orphan cleanup. It never renders credential
  values or instance `config_json` contents.
- HaloPSA and ConnectWise intentionally document both appliance-wide env setup
  and the existing per-client instance flow; no request payload or backend
  contract was changed.

## Version & Compatibility Evidence

- No version or API changes. The existing `ui/package-lock.json` was installed
  with `npm ci` and remained unchanged; no dependency bump was needed. The
  existing compatible toolchain resolved Vite 8.2.2, Vitest 4.1.11, React
  19.2.8, TypeScript 7.0.2, and Playwright 1.62.1 during validation.
- Remaining compatibility concern: the existing Vite config-loader warning and
  large production chunk warning are unchanged and outside this task.

## Open Questions

- None.

## Test Results

- Targeted tests: 4 files, 37 tests passed.
- Full suite run 1: 60 files, 298 tests passed.
- Full suite run 2: 60 files, 298 tests passed.
- Production build passed after TypeScript compilation.
- One earlier full-suite attempt had a transient 5-second Sidebar test timeout;
  the isolated Sidebar test and both subsequent full suites passed.

## Diff Summary

- Connector cards now explain their real setup source and gates. The advanced
  vault explains when names affect env-backed providers. Instance credential
  fields and partial failures now describe encrypted storage without changing
  the connect/vault sequence.

## Requested Review Focus

- narrow diff review
