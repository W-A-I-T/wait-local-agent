# Review

## Changed Files

- Docker/Compose defaults and healthcheck: `Dockerfile`, `docker-compose.yml`,
  `.env.example`.
- Runtime safety: config, TrustedHost middleware, backup confinement, vault
  external-key support, and CLI error mapping.
- UI/desktop: onboarding/readiness, parser contract, proxy routes, dynamic
  Tauri sidecar port, and API-base injection.
- CI/docs/tests: deterministic installs, gitleaks, focused backend/UI tests,
  and operator documentation.

## Risk Areas

- Compose healthchecks depend on a role token being supplied through `.env`;
  explicit demo mode remains the only unauthenticated startup path.
- `WAIT_VAULT_KEY` is an additive external-key path. Existing local `vault.key`
  vaults are intentionally retained for compatibility and migration.
- Desktop sidecar port reservation has the normal small bind race between
  releasing the probe listener and starting the child process; health polling
  fails closed if the selected port is not usable.
- The branch does not contain the report's newer connector-instance and
  readiness APIs, so those findings were not invented here.

## Version & Compatibility Evidence

No dependency versions were changed. UI uses the existing Node 22/Vite/Vitest
lockfile, Python remains 3.12, and Rust formatting was checked against the
existing Tauri toolchain. `cargo check` could not finish packaging because the
checkout lacks the expected generated sidecar binary.

## Open Questions

- Human/release owner must decide whether the 1.1.1 checkout should advance to
  the report's proposed 2.0.0-rc.1 metadata; this implementation preserved the
  target checkout's current version.
- A reciprocal Kimi review could not start because Kimi storage is read-only in
  this environment.

## Test Results

Focused backend/config/compose/server-entry/backup tests, UI tests, UI build,
Ruff, Python compileall, git diff checks, and Rust fmt pass. The harness default
full pytest command lacked `PYTHONPATH`; API TestClient requests also hang under
the locally available dependency combination.

## Diff Summary

The diff closes the externally reachable demo defaults, authenticated health,
backup path, vault-key, parser, onboarding, proxy, readiness, and desktop-port
gaps represented in this checkout, while preserving approval and tenant
boundaries.

## Requested Review Focus

- Confirm healthcheck token precedence and demo-mode behavior.
- Confirm backup confinement and external vault-key compatibility.
- Confirm parser values, readiness status mapping, and desktop API-base wiring.
- Confirm whether remaining report findings belong to a newer revision.

## Review Status

- Harness implementation child failed before editing because Codex state storage
  was read-only; the implementation was completed directly in the isolated
  worktree.
- Harness verification passed the four explicit commands; its default command
  was recorded separately as an environment failure.
- Kimi review launch was attempted but failed before review output because its
  storage path was read-only.

## Claude Final Gate — 2026-08-20

Claude reviewed the branch after the invalid API-key environment variable was
unset. Verdict: **do not merge yet**. It accepted the scope and code direction,
but requires a reciprocal Kimi review or recorded waiver, green CI covering the
TestClient security tests, and a real desktop dynamic-port launch/build check.
It also identified and prompted the now-fixed duplicate parser option and SPA
navigation concern, plus the vault external-key migration warning now present
in the docs.
