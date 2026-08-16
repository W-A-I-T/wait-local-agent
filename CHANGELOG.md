# Changelog

All notable changes to WAIT Local Agent will be documented in this file.

## [Unreleased]

### Fixed

- The Founder journey no longer reports an unknown or missing status as complete.
- Successful Power Platform deployment stages, such as solution imports, now
  report `deployment_started: true` after a non-build PAC command runs instead
  of echoing the plan's planning-time flag.

### Added

- Connector-ingested tickets now resolve their client from verified connector
  mappings and quarantine unmapped records instead of writing a mis-tenanted
  ticket; existing explicit-client and local/demo ingestion remains unchanged.
- Admins can now review per-connector sync health and triage unmapped records
  in the Operations → Sync / Reconciliation Center, including a confirm-gated
  action to mark a record as reviewed.
- Operator endpoints now expose connector sync cursors and the quarantine
  (unmapped-records) ledger, including a gated action to mark a record
  resolved for review.
- Canonical assets are now unique per tenant by `(client_id, canonical_id)`,
  allowing the same canonical asset identifier to exist independently across
  clients while preserving asset observation references.
- Provenance fields now preserve a ticket's source system, connector instance,
  remote ticket ID, and remote company ID without requiring a client mapping.
  The ingestion foundation also adds connector cursors and an operator-facing
  quarantine ledger for records that still need identity review.
- A local Clients directory now anchors client identity, connector instances
  can be recorded alongside the existing Settings connector path, and
  external company mappings remain unverified until an operator confirms
  them. A quarantine sentinel keeps unresolved identities visible for later
  review.
- Authenticated operators can now review read-only event deliveries and event history under Automation → Events, including delivery status, targets, timestamps, and detail fields.
- Authenticated operators can now review read-only workflow and playbook schedules under Automation → Schedules, including cadence, next run, status, and job details.
- Admins can now inspect installed Extensions / Packs under System, including
  version, lock/trust state, license requirements, and CLI/router mount status.
- Admins can now review read-only appliance health, update status, and latest hardening evidence from System → Appliance Health.
- Admins can now discover the local MCP server under Integrations → MCP, copy a
  bearer-token connection configuration, and review the published tool catalog
  with its risk, role, approval, and access metadata.
- Admins can now review read-only Connector Instances under Integrations,
  including configured instances, external-company mappings, and verification
  state without exposing credential values.
- Authenticated operators can now search and filter the read-only Smart Action
  catalog under Integrations → Smart Actions and inspect each action manifest.
- The dashboard now exposes MSP Playbooks with tenant publication status, bounded preview and run actions, revision recovery, and event-subscription controls.
- Versioned SQLite schema initialization now records an idempotent baseline in
  `schema_migrations`, enables foreign-key enforcement, WAL, and a bounded busy
  timeout, and inventories FastAPI, Typer, and MCP surfaces against a committed
  classification manifest.
- `LICENSE_HISTORY.md` records the source-license boundary between the preserved
  Apache-2.0 1.x baseline and the AGPL-3.0-only 2.0 development line.
- The Apache-2.0 license text is retained under `LICENSES/Apache-2.0.txt` for the
  preserved baseline and applicable inherited notices.
- `ADDITIONAL_TERMS.md` and `NOTICE` add the WAIT Section 7 attribution,
  origin, and trademark terms for applicable WAIT-copyrighted Community material.
- The operator and end-user interfaces now render a visible `Powered by WAIT`
  Community attribution.

### Changed

- SQLite backups use a WAL-safe snapshot for plain and encrypted round trips.
- Non-demo appliances now default to `WAIT_DEMO_MODE=false` and refuse startup
  without `WAIT_ADMIN_TOKEN`, `WAIT_API_TOKEN`, or an active `msp_admin`
  principal credential.
- The public `main` development line moves to the `2.0.0` development series and
  is distributed as a combined work under GNU Affero General Public License v3
  only (`AGPL-3.0-only`).
- The previously published source through commit
  `903cb595e8f735fcc306a68f2bee150fce58a416` remains available under Apache
  License 2.0 on the preserved `1.x` line; the new source license does not
  revoke those prior grants.
- Community interactive interfaces containing covered WAIT material must retain
  the reasonable visible `Powered by WAIT` attribution under the applicable
  Section 7 terms. Attribution removal or replacement requires an express
  separate commercial branding right.
- Python package metadata ships the AGPL text, WAIT additional terms, NOTICE,
  and preserved Apache license notice together.

### Security

- Work IQ now requires an access token when an MCP endpoint is configured; a
  missing token disables Work IQ as `not_configured` instead of making an
  unauthenticated request.
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
