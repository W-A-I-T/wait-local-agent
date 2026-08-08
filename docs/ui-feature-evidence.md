# UI and API wiring evidence

This matrix records the current audit boundary for the React dashboard and the
local FastAPI appliance. A green row means the surface was exercised against a
demo-safe local API, not merely rendered by a unit test. A yellow row is an
intentional API/CLI surface without a dedicated dashboard screen; it remains
visible here instead of being presented as a completed UI feature.

## Dashboard route evidence

| Route | Primary surface | API family | Evidence |
| --- | --- | --- | --- |
| `/` | Overview and onboarding | `/auth`, `/connectors`, `/workflow-runs`, `/event-history` | Browser render and dashboard smoke |
| `/connectors` | Connector readiness and Hudu readout | `/connectors/*` | Browser navigation and connector status render |
| `/tickets` | Ticket lookup, summary, approval draft | `/connectors/halopsa/*`, `/tickets/*` | Existing UI tests; browser route render |
| `/approvals` | Approval queue and gated execution | `/approval-requests/*`, `/connectors/halopsa/approval-requests/*` | Existing UI tests; browser route render |
| `/analytics` | Filtered operational metrics | `/analytics/summary` | Existing UI tests; browser route render |
| `/agents` | Definition builder, tool catalog, run detail | `/agents/*`, `/tools`, `/agent-runs/*` | Browser created an agent through the real API and ran it against `TCK-1001`; run completed |
| `/backfills` | Preview, queue, pause, cancel, rerun | `/agent-backfills/*` | Existing UI tests; browser route render |
| `/executions` | Run history, detail, artifact download | `/executions/*` | Existing UI tests; browser route render |
| `/knowledge` | Ingest and search | `/knowledge/*` | Existing UI tests; browser route render |
| `/workflows` | Run, inspect, compare | `/workflows/*`, `/workflow-runs/*` | Existing UI tests; browser route render |
| `/templates` | Gallery create/edit/import/export/revisions/run | `/workflow-templates/*` | Existing UI tests; browser route render |
| `/collectors` | Validate, preview, run, export | `/collectors/*` | Existing UI tests; browser route render |
| `/reports` | Hardening, restore exercise, report export | `/reports/*`, `/hardening/*`, `/backup/*` | Existing UI tests; browser route render |
| `/audit` | Event list and exports | `/audit*`, `/audit-events/export` | Browser route render |
| `/scheduled-jobs` | Schedule lifecycle | `/scheduled-jobs/*` | Browser route render |
| `/settings` | Packs, secrets, backups, update check | `/settings/*`, `/packs/*`, `/secrets`, `/backups*`, `/update-check` | Existing UI tests; browser route render |
| `/founder` | Founder pack and Launch Passport boundary | `/founder/*` | Existing UI tests; browser route render; pack-not-installed state is explicit |

All 16 sidebar destinations rendered their expected primary heading through
normal in-app navigation in the local browser. The Vite proxy now covers every
dashboard API family and lets HTML navigations fall through to the SPA; this is
covered by `ui/tests/vite-proxy.test.ts`.

## Backend capabilities without a dedicated dashboard route

These are public, intentionally bounded API/CLI surfaces. They are recorded
here with their actual interface boundary instead of being hidden behind an
unverifiable product claim.

| Capability | Current interface | UI status | Safety boundary |
| --- | --- | --- | --- |
| Smart-action catalog and direct invocation | API, CLI, Agents tool catalog | No standalone screen; tools are selectable in Agents | Role, tenant scope, approval metadata, redacted output |
| Event ingestion and delivery retry | `/automation/*`, CLI | No standalone screen | Authenticated event types, idempotency, tenant checks, bounded retries |
| Technician chat and persisted sessions | `/technician/chat*`, CLI | No standalone screen | Technician role, tenant/principal scope, bounded parser and history |
| End-user local ticket support | `/end-user/tickets*` | No operator screen; separate end-user API | Separate end-user token, requester and tenant scope |
| Syncro, ServiceNow, Autotask, IT Glue, Confluence, SharePoint, M365, and RMM provider detail routes | API, CLI, Agents tool catalog | No provider-specific dashboard screen | Read-only or approval-gated provider contracts; disabled live calls remain reported as blocked |
| Founder Pack implementation | Public `/founder/*` contract | Founder screen reports pack boundary | Stable `501`/unconfigured responses; no fake scan result |

## Validation record

- UI tests: 17 files, 65 tests passed.
- UI production build: passed.
- Ruff, mypy, Bandit, and public-surface audit: passed in the isolated project
  environment.
- Browser: Agents create/run flow completed against the real local API; all
  sidebar routes rendered through in-app navigation.
- Dependency audit: repository-locked environment reports no known Python
  dependency vulnerabilities; the editable project itself is intentionally
  excluded from the third-party scan.
- Backend full pytest: the local environment's FastAPI/Starlette `TestClient`
  hangs even on a minimal FastAPI health app; the application suite therefore
  needs a clean CI run before it can be called fully verified.

Expected safety states remain visible: connector probing and writes are shown
as blocked when their explicit flags or credentials are absent, and optional
Launch Passport/Founder Pack connectivity reports its unconfigured boundary.
