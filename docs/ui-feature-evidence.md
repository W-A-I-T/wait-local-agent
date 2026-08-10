# UI and API wiring evidence

This matrix records the current audit boundary for the React dashboard and the
local FastAPI appliance. A green row means the surface was exercised against a
demo-safe local API, not merely rendered by a unit test. A yellow row is an
intentional API/CLI surface without a dedicated dashboard screen; it remains
visible here instead of being presented as a completed UI feature.

## Dashboard route evidence

| Route | Primary surface | API family | Evidence |
| --- | --- | --- | --- |
| `/` | Overview and onboarding, event-delivery history and bounded retry | `/auth`, `/connectors`, `/workflow-runs`, `/event-history`, `/automation/event-deliveries*` | Browser render and dashboard smoke; failed deliveries expose a role-aware retry control and never show event payload secrets |
| `/connectors` | Connector readiness and Hudu readout | `/connectors/*` | Browser navigation and connector status render |
| `/tickets` | Ticket lookup, summary, approval draft, local end-user conversation review, support reply, and manually prepared HaloPSA message-sync approval | `/connectors/halopsa/*`, `/tickets/*` | Existing UI tests; browser route render; sync requires explicit client mapping and remote ownership verification |
| `/approvals` | Approval queue and gated execution | `/approval-requests/*`, `/connectors/halopsa/approval-requests/*` | Existing UI tests; browser route render |
| `/analytics` | Filtered operational metrics and operator-priced model usage estimates | `/analytics/summary` | Existing UI tests; browser route render |
| `/agents` | Definition builder, tool catalog, additional and conditional approval-rule editor (ticket priority/status/requester role), edit/version lifecycle, revision compare/restore, run detail | `/agents/*`, `/tools`, `/agent-runs/*` | Existing UI tests cover create/run/edit/history/compare/restore and conditional rule submission; local Chromium smoke verified render and visible ServiceNow and Autotask note/time-entry/status/resolution/assignment approval tools against a fresh local database |
| `/backfills` | Preview, queue, pause, cancel, rerun | `/agent-backfills/*` | Existing UI tests; browser route render |
| `/executions` | Run history, detail, artifact download | `/executions/*` | Existing UI tests; browser route render |
| `/knowledge` | Ingest and search | `/knowledge/*` | Existing UI tests; browser route render |
| `/workflows` | Run, inspect, compare | `/workflows/*`, `/workflow-runs/*` | Existing UI tests; browser route render |
| `/templates` | Gallery create/edit/import/export/revisions/run | `/workflow-templates/*` | Existing UI tests; browser route render; import control is enabled only after a JSON artifact is selected and imports a disabled local copy for review |
| `/collectors` | Validate, preview, run, export | `/collectors/*` | Existing UI tests; browser route render |
| `/reports` | Hardening, restore exercise, deterministic client QBR, automation-opportunity, and recurring-service-review generation, report detail/export | `/reports/*`, `/hardening/*`, `/backup/*` | Existing UI tests cover generation controls and evidence states; browser route render |
| `/audit` | Event list and exports | `/audit*`, `/audit-events/export` | Browser route render |
| `/scheduled-jobs` | Workflow, agent, and client-report schedule lifecycle, including recurring-service-review report target | `/scheduled-jobs/*` | Browser route render; UI tests create QBR and recurring-service-review schedules; backend tests cover scheduled execution |
| `/settings` | Packs, secrets, backups, acknowledgement-gated restore, update check, admin-triggered model health | `/settings/*`, `/settings/providers/health`, `/packs/*`, `/secrets`, `/backups*`, `/update-check` | Existing UI tests; browser route render |
| `/founder` | Founder pack and Launch Passport boundary | `/founder/*` | Existing UI tests; browser route render; pack-not-installed state is explicit |

All listed sidebar destinations rendered their expected primary heading through
normal in-app navigation in the local browser. The Vite proxy now covers every
dashboard API family and lets HTML navigations fall through to the SPA; this is
covered by `ui/tests/vite-proxy.test.ts`.

## Backend capabilities without a dedicated dashboard route

These are public, intentionally bounded API/CLI surfaces. They are recorded
here with their actual interface boundary instead of being hidden behind an
unverifiable product claim.

| Capability | Current interface | UI status | Safety boundary |
| --- | --- | --- | --- |
| Smart-action catalog and direct invocation | API, CLI, Agents tool catalog | No standalone screen; tools are selectable in Agents | Role, tenant scope, approval metadata, redacted output; SLA/stale tools require explicit thresholds and timestamp evidence; M365 onboarding/offboarding/password-reset/authentication-method-removal are admin-only, approval-gated, and never persist credentials |
| Event ingestion and delivery retry | `/automation/*`, Overview | Overview lists tenant-scoped delivery status and exposes manual retry for failed deliveries within the retry budget; event ingestion remains an API/webhook surface | Authenticated event types, idempotency, tenant checks, persisted `max_retries` 0-10, persisted `retry_delay_seconds` 1-3600, bounded automatic retries, and technician/admin-only manual retry |
| Technician chat, plan previews, notifications, and persisted sessions | `/technician/chat*`, `/technician-chat`, `/smart-actions/communication-send/invoke`, CLI | Dedicated technician screen supports session create/select/send/close, bounded plan previews, and Teams/Slack notification approval preparation; explicit `plan ... TCK-*` requests reuse the reviewed planner, while the CLI and API remain available | Technician role, tenant/principal scope, bounded parser and history; notification requests reuse the audited communication action and remain approval-gated before configured delivery |
| End-user local ticket support | `/end-user/config`, `/end-user/tickets*`, `/tickets/{ticket_id}/end-user-messages`, `/tickets/{ticket_id}/end-user-messages/{message_id}/halopsa-drafts`, `/end-user` | Dedicated end-user surface supports token save, scoped branding load, ticket creation, status lookup, requester/support messages, and technician escalation; the Tickets screen supports operator conversation review, local support replies, and manual HaloPSA approval-draft preparation; it is separate from the operator shell | Separate end-user token, fixed requester and tenant scope, technician/admin-only operator actions, isolated end-user message store, explicit local-to-remote client mapping, remote ticket ownership verification, approval-gated non-hidden HaloPSA note, bounded display-only branding, end-user-safe responses, and no technician/admin tools in the end-user surface |
| Ticket lifecycle history and historical resolution metrics | `/tickets/{ticket_id}/status-history`, `/analytics/summary`, CLI analytics summary | Analytics metric on dashboard; history remains an API/CLI detail surface | Uses only explicit local/imported transitions; existing snapshots are not treated as historical evidence |
| Syncro, ServiceNow, Autotask, IT Glue, Confluence, SharePoint, M365, and RMM provider detail routes | API, CLI, Agents tool catalog | No provider-specific dashboard screen; IT Glue, SharePoint, Kaseya, and ScreenConnect device/session lookup tools are selectable in `/agents` | Read-only or approval-gated provider contracts; IT Glue and SharePoint searches are tenant/site scoped, capped at 50 results, redacted, and blocked when live probing is disabled; Kaseya VSA X reads require a local client-to-organization map and re-filter returned rows; ScreenConnect reads require a local client-to-session UUID map and documented RESTful API Manager configuration; ScreenConnect alerts/scripts/commands remain explicit unavailable results; ServiceNow work-note/state/assignment/resolution-metadata and Autotask ticket-note/status/resolution tools are approval-gated; disabled live calls remain reported as blocked |
| Founder Pack implementation | Public `/founder/*` contract | Founder screen reports pack boundary | Stable `501`/unconfigured responses; no fake scan result |
| M365 password/MFA administration | `/connectors/m365/users/password-reset-drafts`, `/connectors/m365/users/authentication-method-drafts`, CLI, Agents tool catalog | API/CLI/tool-catalog surface; no dedicated dashboard control | Password comes only from a `WAIT_M365_TEMP_...` vault reference; MFA removal is one explicitly identified allowlisted method; admin approval and tenant scope are required |
| Communication delivery receipts | `GET /smart-actions/runs`, `wait-local-agent smart-actions runs` after an approved `communication-send` | API/CLI surface; no dedicated communication-history screen | Receipt is local and opaque; acceptance timestamp/status are bounded; webhook HTTP status is retained; provider bodies, credentials, and provider-issued callback IDs are not exposed |

## Validation record

- UI tests: 21 files, 84 tests passed.
- UI production build: passed.
- Real-browser smoke on `main` after IT Glue content-search merge: `/agents`
  loaded with `/agents` and `/tools` returning `200`; the IT Glue documentation
  search control was selectable and the bounded plan-preview control surfaced a
  `400 ticket was not found in the requested scope` response for an empty local
  ticket fixture rather than claiming success.
- SharePoint search is exposed through the same Agents catalog contract and
  covered by the merged backend/UI CI gates; provider-backed search remains
  mocked in tests because no external tenant credential was supplied.
- Ruff, mypy, Bandit, and public-surface audit: passed in the isolated project
  environment.
- Browser: Agents create/run flow completed against the real local API; all
  sidebar routes rendered through in-app navigation.
- Scheduled report UI test: `/scheduled-jobs` switched to Client report and
  submitted a tenant-scoped QBR schedule with a bounded rolling period through
  `POST /scheduled-jobs`.
- Local Chromium smoke after merged commit `470dbd2`: passed for `/agents`; the
  real local API returned HTTP 200 for `/agents`, `/tools`, `/connectors`, and
  the dashboard's supporting requests, with no browser errors. The tool catalog
  visibly included `Autotask add ticket note · approval`, `Autotask update ticket
  status · approval`, `Autotask update ticket resolution · approval`, `Autotask
  assign ticket · approval`, `Autotask add time entry · approval`, and the
  ServiceNow approval tools. A subsequent Chromium sweep visited all 18 operator
  routes plus the standalone `/end-user` surface; every page rendered and the
  browser reported no errors. The end-user surface remains direct-link only so
  its separate token boundary is not confused with the operator shell.
- Dependency audit: repository-locked environment reports no known Python
  dependency vulnerabilities; the editable project itself is intentionally
  excluded from the third-party scan.
- Backend full pytest: the local environment's FastAPI/Starlette `TestClient`
  hangs even on a minimal FastAPI health app; the application suite therefore
  needs a clean CI run before it can be called fully verified.

Expected safety states remain visible: connector probing and writes are shown
as blocked when their explicit flags or credentials are absent, and optional
Launch Passport/Founder Pack connectivity reports its unconfigured boundary.
