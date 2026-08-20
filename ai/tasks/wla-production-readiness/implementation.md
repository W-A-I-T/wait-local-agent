# Implementation Notes

## Summary

Implemented the safe, applicable production-readiness fixes for the verified
`W-A-I-T/wait-local-agent` checkout. This checkout is the older 1.1.1 line and
does not contain the report's newer connector-instance/readiness model, so the
changes use its existing connector status and approval interfaces.

- Disabled demo mode by default across Settings, Docker, Compose, and the
  example environment; bound direct Docker and published Compose ports to
  loopback while keeping the Compose API reachable from the UI container.
- Made Compose healthchecks authenticate with any configured operator role
  token and changed UI dependency installation to deterministic `npm ci`.
- Added TrustedHost validation and confined API/CLI backup paths to the
  appliance data directory, with safe 4xx handling for rejected paths.
- Added optional externally supplied `WAIT_VAULT_KEY` support so new vaults
  can avoid colocating a Fernet key file with encrypted secrets; legacy local
  key files remain compatible.
- Corrected Knowledge parser values and normalized `auto` to the backend's
  accepted default parser name, with UI coverage for every option.
- Reworked onboarding around the four real surfaces in this branch, removed
  fake credential validation, linked to connector configuration, refreshed
  readiness after completion, and retained shipped demo ticket `TCK-1001`.
- Made readiness reflect this branch's actual `configured`/`ready` connector
  statuses, added `/msp` and `/mcp` proxy route coverage, and wired the desktop
  sidecar to an ephemeral loopback port with an injected API base.
- Added gitleaks coverage and deterministic desktop dependency installation in
  CI/release workflows, plus documentation for explicit demo and vault setup.

## Commands Run

- Focused backend tests (`config`, `compose`, `server_entry`, `backup`) — passed, 41 tests.
- `npm --prefix ui test -- --run` — passed, 49 files / 232 tests.
- `npm --prefix ui run build` — passed.
- Ruff, Python `compileall`, `cargo fmt --check`, and `git diff --check` — passed.
- `cargo check` resolved dependencies but stopped in the existing Tauri build
  script because the generated sidecar binary is absent from the checkout.
- Reciprocal Kimi review launch was attempted; reviewer storage was read-only.
- Added a regression test for late Tauri API-base injection; the API URL helper
  now reads the runtime base for each request instead of relying on module-load
  timing.

## Files Touched

- Runtime/deployment: `.env.example`, `Dockerfile`, `docker-compose.yml`,
  `src/wait_local_agent/config.py`, `src/wait_local_agent/api/app.py`,
  `src/wait_local_agent/backup.py`, `src/wait_local_agent/cli.py`,
  `src/wait_local_agent/vault.py`.
- UI/desktop: dashboard/readiness, proxy, Knowledge, onboarding, and
  `desktop/src-tauri/src/main.rs`, `desktop/src-tauri/tauri.conf.json`.
- Tests/workflows/docs: focused backend/UI tests, GitHub workflows, README,
  appliance/demo docs.

## Follow-Up

- This target has no connector-instance routes, four readiness endpoints, or
  separate backup-root setting from the report; those findings require a newer
  target revision or separately scoped feature.
- Full desktop packaging still requires the platform-generated sidecar and
  signing/updater artifacts; no release or deployment was performed.
- The local Starlette TestClient suite hangs during API requests under the
  available dependency combination, so the focused API route test could not
  complete here; static, backup, config, UI, build, and focused checks passed.
