# Review

## Changed Files

- `ui/src/api/types.ts`
- `ui/src/screens/{ConnectorInstances,Playbooks,ScheduledJobs,McpIntegration,Audit,Tickets}.tsx`
- Focused UI tests under `ui/tests/`

## Risk Areas

- Connector edits deliberately exclude credential references; configuration JSON is validated as an object before PATCH.
- Subscription PATCH is restricted to the backend-verified `input_mapping` and `enabled` fields; immutable binding fields are shown read-only.
- MCP initialization creates a server session as required by the protocol; the screen does not call tools or send the initialized notification.
- ConnectWise drafts remain approval drafts and reuse the existing write gating; no direct provider write was introduced.
- Date-only audit inputs are sent as UTC day boundaries (`00:00:00Z` through `23:59:59Z`).

## Version & Compatibility Evidence

- No dependency or backend API changes were made. Route/request compatibility was verified against the checked-out `app.py` models and handlers.
- `npm ci` honored the existing lockfile. Observed versions: Node `v24.16.0`, npm `11.13.0`, Vite `8.2.2`, Vitest `4.1.11`, TypeScript `7.0.2`; `npm outdated --json` reported no updates.
- Remaining compatibility risk is limited to existing Vite warnings about native config loading and chunk size; neither is introduced by this task.

## Open Questions

- None for implementation. Confirm the intended review/merge gate before landing the branch.

## Test Results

- `npm test -- --run`: passed three times, 65 files / 339 tests on each run.
- `npm run build`: passed.
- `git diff --check`: passed.

## Diff Summary

- Six UI dead ends now have reachable, model-compatible paths while preserving existing admin/technician/write gates and approval flows. Added focused regression tests for connector edits, subscription PATCH shape, scheduled playbook creation, MCP live/fallback states, audit export query shape, and ConnectWise drafts.

## Requested Review Focus

- Verify the six request payloads against the backend models, especially immutable subscription fields and MCP JSON-RPC `result` handling; check that no credential material enters UI output or draft payloads.
