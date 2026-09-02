# Changelog

All notable changes to WAIT Local Agent will be documented in this file.

## [Unreleased]

### Breaking

- Power Platform solution packages now use the proven XML layout under
  `Other/` instead of YAML; emitted file paths and package digests change, and
  custom connectors are reported as design-only rather than deployable source.

- Power Platform source package metadata now includes `design_only_components`;
  `package_status` may be `partial_source`, and package digests change for
  flow-bearing solutions.

- Power Automate source packaging now rejects flat `trigger`/`steps` flow
  artifacts with an explicit error; trigger and actions must be nested under
  `power_automate`.

- The external-tester milestone is `2.0.0-rc.1`; Python packaging uses the
  normalized PEP 440 version `2.0.0rc1`.

- Provider connector origins now require HTTPS by default. Set
  `WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT=true` only when plain HTTP is
  deliberately required for all provider origins on a trusted network.

### Removed

- Removed the duplicate `GET /audit/export` route; use
  `GET /audit-events/export` with the `format` query parameter.

### Changed

- Microsoft Graph reads now use bounded throttling retries with `Retry-After`,
  early client-credential token refresh, typed provider error responses, and
  loud pagination-cursor failures; Graph writes remain single-attempt.

- Microsoft 365 and RMM connector resolution now reports its selected tier and
  keeps explicit client-scoped requests from falling back to MSP-wide or
  environment credentials.
- Founder browser scans now advance through the appliance scheduler, with
  bounded persisted polling progress and truthful status timestamps.
- Diagnostics now state that support upload is unavailable in this edition;
  local bundle download remains available.

- Scheduled jobs now declare single-instance execution and a bounded 300-second
  misfire grace period; startup rejects multi-worker configurations while the
  in-process scheduler is enabled.
- Capability grants are now part of the canonical startup migration sequence,
  so authenticated requests no longer run migration checks on the hot path.
- The operator shell now reports the aggregate write gate across configured PSA
  connectors, keeps administrator-only surfaces behind role checks, and makes
  the separate customer portal boundary explicit in navigation.
- Appliance Health now lets administrators confirm and run an on-demand
  backup, then review its persisted ID, status, size, and timestamp. The
  Automation Discovery panel now exposes pack status, categories, mapping
  readiness, and credential-free time-entry evidence import with role-aware
  loading and error states.
- Power Platform BUILD stages now stop after the local unmanaged solution pack;
  `pac solution check` is no longer run as part of BUILD because checker
  findings are advisory and the command requires an active cloud environment.

- The Solutions Architect screen (renamed from Consultant) now surfaces the
  architecture decision engine, including per-component chosen targets,
  rationale, alternatives, requirements, and a decision-engine summary.
- Setup readiness now uses required administrator, client, connector, and
  verified-mapping steps instead of a settings-endpoint heuristic; a Setup
  status checklist shows what remains.
- Reorganized the sidebar into product groups for Operations, Automations,
  Solutions Architect, Evidence & Reports, and Setup, with low-frequency and
  admin surfaces in a collapsed System / Advanced drawer. Renamed the
  Consultant navigation label to Solutions Architect; routes are unchanged.

### Security

- Smart-action invoke now rejects caller-supplied `_approval_completed` payload
  fields to prevent approval-gate bypasses; the invoke route returns 400 for
  reserved-field and validation errors.
- Per-connector-instance read clients now resolve credentials only from the
  local vault, isolate provider settings, force read-only behavior, and send
  outbound calls through SSRF-pinned transport.
- The `__quarantine__` client is now reserved and non-assignable: client
  status changes, principal roles, connector-instance bindings, and client
  connector mappings cannot target it. Existing upgraded bindings are logged
  at startup for operator review.
- Per-connector-instance outbound calls now use a host allowlist, pinned-IP
  DNS resolution, globally-routable address checks, proxy and redirect
  blocking, identity content encoding, and a bounded response stream.
- Provider-ticket ingestion persists unresolved tickets under the reserved
  quarantine tenant while still preventing a re-reported external ticket under
  a different company from overwriting or re-attributing another client's
  ticket; ownership collisions remain recorded for reconciliation.
- Provider-ticket audit entries no longer copy provider subjects into the
  unredacted audit stream; ingested tickets use a static detail and internal
  ticket identifier.

### Fixed

- Removed the unreachable local-open auth presentation, made wizard progress
  controls match their available handlers, and replaced misleading empty
  ticket/demo states with actionable connector guidance.
- Fixed Settings update checks and collector exports to use their backend POST
  contracts, routed desktop Microsoft sign-in through the configured API base,
  and added frontend route/method contract guards for the development proxy.
- Microsoft Admin Graph routes now use the client scope authorized for the
  request, and fail closed when that client has no active connector.
- Founder Launch Passport polling no longer remains queued after a browser
  launch, and terminal scan states are not polled again.
- The diagnostics API and screen no longer advertise a support upload action
  that always fails; upload refusal is consistently reported as `501`.
- SPA HTML fallbacks now opt out of caching and vary on `Accept`, API requests
  explicitly negotiate JSON, and the dashboard no longer repeatedly rate-limits
  its local write-health check or Halo ticket bootstrap request.

- Production trusted-host defaults no longer include the test-only `testserver`
  host, and refused demo-mode backup requests no longer create audit events.
- Power Platform deployment and rollback execution now enforce the minimum CLI
  version and block when the installed version cannot be determined.

- Flaky diagnostics, Sidebar navigation, Solutions Architect, and Microsoft Administrator tests now isolate legitimate timing changes and avoid repeated full-tree queries under coverage.

- Power Platform package deployability is now computed from emitted component
  readiness instead of being asserted by a hardcoded value.

- Power Platform deployment and rollback approvals now reject re-execution
  after any terminal execution status, preserving the original promotion
  evidence.

- Flow-bearing package digests now reflect the design-only flow record rather
  than a fake `flow.yml` source file.

- The Solutions Architect screen now loads each section independently, so a
  failed `/consultant/*` sub-request does not blank the blueprint list or
  architecture view; affected sections show a scoped load notice.
- The Tickets workspace now caches each selected ticket's Summary, Notes,
  Status History, and Context tab data, so switching between tabs no longer
  refetches already-loaded data; a tab-scoped Refresh button and the app-wide
  dashboard refresh both invalidate the cache and force a fresh load, and the
  cache is cleared when the selected ticket changes.
- The Clients screen now loads under the local development server because
  `/clients` is included in the Vite dev-proxy allowlist.
- Automation-opportunity reports now require at least 5 attempts, 3 successes,
  an 80% success rate, positive declared savings, and a 30–90 day window;
  candidate rows expose attempts, failures, success rate, and approval burden
  instead of labeling a single success as repeated.
- The Founder journey no longer reports an unknown or missing status as complete.
- Successful Power Platform deployment stages, such as solution imports, now
  report `deployment_started: true` after a non-build PAC command runs instead
  of echoing the plan's planning-time flag.

### Added

- Added `WAIT_PAC_PATH` support for Power Platform CLI installations that are
  not available on `PATH`.

- Added administrator-only appliance diagnostics, deterministic redacted
  support bundles, local preview/download flows, bounded private rotating logs,
  validated request correlation IDs, support CLI commands, and the System
  Diagnostics & Support screen. Automatic support transfer remains disabled.
- Added a customer-facing licensing panel, a local-audit privacy notice, and a
  technician onboarding path through tickets, triage, planning, approval, and
  evidence.

- The Solutions Architect screen can now generate a disabled draft playbook
  from a selected blueprint in one click; review and enable the draft in
  Playbooks.

- The Solutions Architect can now generate a disabled draft playbook from a
  blueprint at `POST /consultant/blueprints/{id}/generate-playbook`. The
  deterministic compiler binds only to existing workflow or agent primitives,
  persists tenant-scoped provenance and revisions, and leaves enabling to an
  explicit administrator action.

- Connector Instances now include an admin-only "Connect a system" flow for
  HaloPSA and ConnectWise that stores provider credentials in the local vault
  and keeps only the credential reference plus non-secret configuration on the
  connector instance.
- Connector Instances can now discover HaloPSA and ConnectWise companies,
  map them to WAIT clients, and verify mappings, completing the connect →
  discover → map → verify → sync journey.

- Client details now include a read-only Operational graph tab showing linked
  entities and relationships.

- Added a client-scoped, read-only Smart Action Runs screen with run history
  and detail views for status, actor, output, evidence, and errors.

- Added a reusable read-only connector browse panel, with Autotask ticket and
  company browsing as its first provider (health and paginated lists).

- A Microsoft 365 Actions console can now draft offboarding, password-reset,
  and device-reboot actions. Drafts are approval-gated and route through the
  existing Approvals queue.

- The Tickets screen is now a unified multi-provider workspace with a canonical
  client-scoped ticket list and Summary, Notes, Status History, and Context
  tabs for ticket evidence and operational-graph relationships.

- RMM device and alert inventory now persists into the client operational graph
  with deterministic `alerted_on` links. Viewers can read a bounded client
  graph, and MSP operators can trigger an RMM graph sync.
- Failed event deliveries can now be retried from the Events screen when retry capacity remains.
- Administrators can now install packs from the Extensions / Packs screen and see the result inline.

- Client Operational Graph PR1 adds migration v7 with deterministic,
  client-scoped `external_entity_refs` and `entity_links`, bounded graph
  traversal, and `GET /tickets/{id}/context`.
- HaloPSA and ConnectWise approval-gated ticket writes now perform a minimal
  read-back verification after the provider accepts the write. Approval
  records distinguish `verified`, `unverified`, and `submitted`; only a
  confirmed field or note read-back is `verified`, and queued/submitted does
  not imply verification.
- Administrators can now trigger a manual connector "Sync now" from the
  Connector Instances screen and review its poll summary inline.
- Founder Launch Passport scans now return a deterministic scan-to-scan delta
  for dependencies, manifests, and files, including added, removed, changed,
  and unknown classifications plus a predecessor link.

- Users can now execute Microsoft 365 and Teams approvals directly from the
  Approvals screen; execution was previously limited to HaloPSA, and Teams had
  no UI execute path.
- HaloPSA and ConnectWise read responses now expose raw/dropped row counts,
  HTTP status, and bounded `Retry-After` metadata so a future poller can
  distinguish a valid empty page from dropped rows, malformed envelopes,
  blocked reads, redirects, throttling, and provider failures.
- A Clients directory and app-shell client selector now expose the available
  client context while existing screens retain their current behavior until a
  later client-scoping phase.
- Administrators can now confirm connector mappings with the re-tenant count,
  review quarantined tickets by connector, and reclassify tickets from the
  Operations → Sync / Reconciliation Center.
- A per-connector-instance read-client factory for HaloPSA and ConnectWise
  with vault-resolved credentials and strict per-instance isolation.
- A bounded synchronous HaloPSA/ConnectWise ingestion poller with provider
  adapters, raw-page EOF validation, sticky degradation, retry/deadline
  controls, and token-fenced lease revalidation before each page write.
- Connector-ingested tickets now resolve their client from verified connector
  mappings and persist unresolved records in the reviewable quarantine tenant;
  mapping verification re-tenants matching tickets. Ticket identity is stable
  per connector instance and local ingestion requires an explicit active
  client.
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
- Schema migration v5 preserves every existing ticket ID, backfills legacy
  tenant references, enforces `tickets.client_id`, and adds the partial unique
  `(connector_instance_id, external_id)` identity index. Provider upserts use a
  frozen deterministic identity and return the persisted legacy ID for history
  and audit writes.
- Schema migration v6 adds nullable fencing metadata for connector poll
  cursors. Store-level claims are serialized with `BEGIN IMMEDIATE`, distinguish
  granted, locked, and missing-instance outcomes, preserve prior progress, and
  prevent stale workers or legacy cursor writes from overwriting a successor's
  lease. The scheduler and route wiring remain out of scope for this slice.
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

- Normal AllClients ticket reads and ticket analytics now hide the reserved
  `__quarantine__` tenant; explicit tenant-scoped quarantine reads and an
  explicit include opt-in remain available for triage.
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

- Clients now support detail drill-in, administrator create/edit actions, and
  connector-mapping verification from the Clients screen.
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
