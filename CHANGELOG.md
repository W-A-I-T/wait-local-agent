# Changelog

All notable changes to WAIT Local Agent will be documented in this file.

## Unreleased

- Linux draft release checksum publishing now includes RPM (`.rpm`) artifacts in `SHA256SUMS`.
- Version bumped to `1.1.1` across API, Python package, desktop package, and UI/package metadata.

## [1.0.0] - 2026-07-08

### Added

- RBAC-backed bearer token roles for admin, technician, and viewer access across the API, dashboard, and founder endpoints.
- Approver identity capture in approval requests and audit exports.
- Tenant and client boundary support on workflow, approval, scheduled job, and audit records.
- Optional encrypted backup and restore support with the local Fernet vault.
- `wait-local-agent connectors validate` checks for HaloPSA and Hudu credential readiness.
- Scheduled workflow persistence, pause/resume control, and audit logging.
- Signed update-check client support with pinned public keys and signature verification.
- Open-core pack loader plus `wait-local-agent packs list`, `status`, and `install`.
- Public founder API and CLI surface that delegates to an installed founder pack when available.
- Bearer token API gate outside local demo mode via `WAIT_API_TOKEN` and `WAIT_DEMO_MODE`.
- Optional Fernet-backed local secrets vault and `wait-local-agent secrets` CLI commands.
- JSON and CSV event history export through API and CLI.
- Expanded approval payload redaction for common secret, token, API key, bearer, and authorization key variants.
- `scripts/install.sh` Docker Compose install helper.
- Synthetic public demo data under `demo/`.
- Launch documentation for local demo, appliance install, connector setup, security model, launch checklist, and open-core boundary.
- GitHub issue templates for bugs, connector requests, workflow template requests, and security hardening reports.
- Release assets, screenshots, badges, and docs consistency updates for the public 1.0.0 release pass.

### Changed

- Dockerfile, Docker Compose, and `.env.example` now make auth, scheduler, update-channel, and vault defaults explicit.
- `.gitignore` now excludes `packs/` and local vault artifacts.
- README now documents the shipped architecture, screenshots, quickstart, and open-core pack boundary.
- Status, launch checklist, and publication checklist now reflect the shipped Phase 5 to 8 public surfaces.

### Security

- API requests require a configured bearer token when demo mode is disabled.
- Route-level rate limiting is active on public API surfaces, with tighter limits on mutation paths.
- Pack installs and update metadata require signature verification before trust.
- Live writes remain disabled by default and still require approval before connector mutation.
- Hudu remains read-only in the public repo.

### Not included

- No proprietary MSP Pack or Founder Pack implementation was added.
- No cloud-first runtime, cloud fallback default, live sync, real connector credentials, or AGPL-derived code was added.
