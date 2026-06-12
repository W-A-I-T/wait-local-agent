# Changelog

All notable changes to WAIT Local Agent will be documented in this file.

## Unreleased

### Added

- Bearer token API gate outside local demo mode via `WAIT_API_TOKEN` and `WAIT_DEMO_MODE`.
- Optional Fernet-backed local secrets vault and `wait-local-agent secrets` CLI commands.
- JSON and CSV event history export through API and CLI.
- Expanded approval payload redaction for common secret, token, API key, bearer, and authorization key variants.
- `scripts/install.sh` Docker Compose install helper.
- Synthetic public demo data under `demo/`.
- Launch documentation for local demo, appliance install, connector setup, security model, launch checklist, and open-core boundary.
- GitHub issue templates for bugs, connector requests, workflow template requests, and security hardening reports.

### Changed

- Dockerfile, Docker Compose, and `.env.example` now make auth and vault defaults explicit.
- `.gitignore` now excludes `packs/` and local vault artifacts.
- Status and publication checklist now reflect implemented Phase 1 safety fixes and remaining Phase 5 hardening.

### Security

- API requests require a configured bearer token when demo mode is disabled.
- Live writes remain disabled by default and still require approval before connector mutation.
- Hudu remains read-only in the public repo.

### Not included

- No proprietary MSP Pack or Founder Pack implementation was added.
- No cloud-first runtime, cloud fallback default, live sync, real connector credentials, or AGPL-derived code was added.
