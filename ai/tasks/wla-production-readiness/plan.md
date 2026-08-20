# Plan

## Task ID

`wla-production-readiness`

## Goal

Make WAIT Local Agent safe and usable for external testers by repairing the
first-run Docker/CLI paths, aligning the UI with the real connector/readiness
contracts, and closing the documented deployment and release-readiness gaps.
Preserve the local-first, deterministic, approval-gated architecture.

## Constraints

- Work only in `W-A-I-T/wait-local-agent`; do not modify other repositories.
- Demo mode remains explicit, loopback-only, write-disabled, and never the
  default deployment mode.
- Do not expose secrets, service credentials, or raw connector payloads.
- Preserve existing tenant scope, RBAC, approval, audit, parser, and connector
  interfaces unless a compatibility-preserving fix is required.
- Human retains merge, tag, release, and deploy authority.

## Acceptance Tests

- Dockerfile and `.env.example` default to non-demo operation; direct Docker
  startup is loopback-bound and Compose publishes only on `127.0.0.1`.
- Compose healthchecks authenticate successfully in configured mode and the UI
  starts; demo mode remains available only when explicitly enabled.
- Documented CLI, Docker, demo-seeding, backup, and secret-vault commands work
  from the shipped image or are corrected to match shipped assets.
- Knowledge UI and onboarding send only parser names accepted by
  `parser_for_name`; tests cover every UI parser option.
- Onboarding follows the four real readiness requirements, deep-links to the
  actual configuration surfaces, refreshes readiness after return, and uses a
  shipped demo ticket.
- `/msp` and `/mcp` UI requests are proxied and covered by a complete route
  contract test.
- Backup paths are confined to the configured backup root; vault keys are not
  silently colocated with ciphertext for new non-demo vaults; approval
  self-approval is rejected.
- Connector-instance host allowlisting, trusted-host validation, and redacted
  ingestion diagnostics are documented and tested.
- CI runs deterministic UI installs, backend/security checks, UI coverage,
  gitleaks, Rust checks, and a sidecar build smoke test.
- A Compose boot/integration smoke path and desktop dynamic-port/health tests
  cover the external-tester path.
- Version metadata is aligned and release documentation distinguishes published
  tester releases from draft releases and updater requirements.

## Version & Compatibility Evidence

- Preserve the repository-pinned Python 3.12, Node 22, Rust/Tauri, Vite, and
  Vitest toolchain; do not upgrade dependencies unless required by an existing
  lockfile or CI failure.
- Align application metadata for the `2.0.0-rc.1` tester milestone, using the
  PEP 440 equivalent where Python metadata requires it.
- Validate the existing `ui/package-lock.json`, Docker Compose schema, Tauri
  updater contract, and current API route/parser contracts before changing them.

## Files Expected

- Dockerfile, docker-compose.yml, `.env.example`, CLI/config/security,
  backup/vault/approval/poller modules and their focused backend tests.
- UI API/proxy, Knowledge, onboarding/readiness surfaces and focused Vitest
  coverage.
- CI workflows, desktop Rust/Tauri runtime, packaging/release documentation,
  and Compose/browser smoke coverage.

## Out Of Scope

- OAuth implementation for M365.
- Acquisition of Apple, Windows, or other signing certificates.
- New connector capabilities, paid-pack implementation, production deployment,
  or automatic tag/release publication.
- Unrelated cleanup or architectural rewrites.

## Handoff To

codex

## Review Focus

- Authentication and network exposure in Docker/demo/healthcheck paths.
- Vault-key migration and backup filesystem boundaries.
- Approval requester/approver identity enforcement.
- Parser and onboarding/readiness contract correctness.
- Desktop dynamic-port API-base wiring and release updater behavior.
