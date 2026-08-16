# Changelog

All notable changes to WAIT Local Agent will be documented in this file.

## [Unreleased]

### Added

- Versioned SQLite schema initialization now records an idempotent baseline in
  `schema_migrations`, enables foreign-key enforcement, WAL, and a bounded busy
  timeout, and inventories FastAPI, Typer, and MCP surfaces against a committed
  classification manifest.

### Changed

- SQLite backups use a WAL-safe snapshot for plain and encrypted round trips.
- Non-demo appliances now default to `WAIT_DEMO_MODE=false` and refuse startup
  without `WAIT_ADMIN_TOKEN`, `WAIT_API_TOKEN`, or an active `msp_admin`
  principal credential.

### Security

- Explicit demo mode is bounded: provider writes and deployments remain
  disabled, and `/secrets` returns HTTP 403.
- Principal identity supports per-client roles and a global `msp_admin` role;
  principal credentials are stored as SHA-256 hashes rather than raw
  credentials.
- Client-bearing API routes now resolve one fail-closed `ClientScope`; bootstrap
  admin tokens and `msp_admin` principals can use explicit cross-client scopes,
  per-client principals remain tenant-bound, and store filters reject
  `None`/empty client IDs.
- Entity routes now derive mutation scope from the stored tenant-bearing entity,
  M365 draft handlers enforce the authenticated client scope, and legacy
  untagged approvals remain restricted to demo mode and appliance operators.

## [1.1.1] - 2026-07-21

### Added

- Connector coverage now includes bounded ConnectWise, Syncro, ServiceNow,
  Autotask, RMM, cloud inventory, identity, and documentation read paths, with
  explicit opt-ins and approval-gated writes where supported.
- Consultant and Microsoft 365 surfaces add deterministic blueprint,
  governance, evaluation, identity, and bounded live Graph context workflows.
- Scheduled workflows, event-triggered agents, bounded retries, cancellation,
  backfills, revision history, rollback, reports, and tenant-scoped run
  evidence are available through the existing runtime.

### Changed

- The API, CLI, dashboard, and desktop app now expose role-scoped operations
  across tickets, approvals, workflows, agents, analytics, reports, and audit
  history.
- Workflow and agent previews, galleries, comparisons, imports, and exports
  remain local, bounded, redacted, and approval-safe.
- Linux release checksum publishing now includes RPM (`.rpm`) artifacts in
  `SHA256SUMS`.
- Version metadata is aligned at `1.1.1` across the API, Python package,
  desktop package, and UI package.

### Security

- Bearer-token RBAC, client tenancy filters, approval identity capture, and
  expanded secret redaction cover the public API and operator surfaces.
- Signed update checks, encrypted backup and restore, conservative connector
  defaults, explicit outbound controls, and approval-before-write guard live
  execution.

### Operations

- Scheduled jobs persist pause, resume, reschedule, cancellation, and audit
  history; active agent runs support bounded cancellation and retry.
- The local demo, desktop installer, pack discovery, founder routes, and
  release validation paths are documented for the public surface.

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
