# User-journey hardening: review map

Starting point: `55f1a0d19eb346ec79a6d940aa5e68dc6dd844c8` on `main`,
Python version `2.0.0rc1`, UI/desktop version `2.0.0-rc.1`.

This is a code and fixture review map, not a claim of browser or production
verification. The source API and compiled SPA were served locally, including
authenticated startup, explicit demo startup, shutdown, restart and persistence.
Browser execution was blocked by the available environment. Docker, Rust and a
desktop display were unavailable. No real provider tenant was used for validation.
The PR validation ledger records commands, results and remaining release gates.

A baseline retry exposed an existing test that could send an external ServiceNow
read for a malformed filter; automatic approval review blocked the action.
The reproduction was then moved to a failure-on-call mock, and the suite now
rejects non-local HTTPX transport requests. Only disposable fixture credentials
were used. The failed baseline attempt is not counted as provider verification.

## Scope and evidence

The map comes from `ui/src/routes.tsx`, each screen's handlers, shared dashboard
and scope helpers, the API routers, CLI registry and desktop shell. The canonical
runtime surface inventory remains in `docs/ai-workflow/surface-coverage.json`
and its fragments, checked against the live route registry by
`tests/test_spine_p0.py` and `tests/test_route_inventory.py`.

Roles below describe the shipped boundaries: V = viewer, T = technician,
A = client administrator, M = MSP administrator, U = supported end-user identity.
Minimum roles do not replace capability grants, provider policy, approval or
scope checks. Selecting a client binds a staff principal's role and data scope
together. With no selection, the least privileged membership applies. Explicit
MSP all-client access remains deliberate. End-user identity does not use the
staff client picker to select an arbitrary requester or tenant.

UI state notes below describe inspected code and component-test contracts.
They have **not** been visually verified at the requested four viewport sizes.
Local persisted results, demo results, fixture provider responses and real
provider verification are different evidence levels.

## Route and action map

| Route | Persona / access / scope | Backing API and service or storage | State and capability boundary |
| --- | --- | --- | --- |
| `/login` | All personas; credential establishes scope | `/auth/login/local`, `/auth/session`, `/auth/role`, optional OIDC; principal hashes and browser sessions | Busy submit, invalid-token error, authenticated redirect; old client selection cleared. OIDC requires configured identity provider. |
| `/` | Staff V+; selected client or explicit MSP all-client view | Dashboard connector, approval, workflow, event and client reads; SQLite and provider status adapters | Loading, setup steps, empty activity, refresh errors. Setup completion is local configuration readiness. |
| `/clients` | V reads; M directory mutations; membership directory | `/clients`, client baselines, mappings, commercial activations; tenant store | Loading/list/empty directory, validated creation, conflict errors, explicit selected detail. Activation is separate from provider connectivity. |
| `/client-discovery` | Administrator UI; M operations; MSP deployment mode | `/setup/mode`, `/discovery/clients`; discovered candidates and mappings | Mode/connector prerequisites, empty candidates, run result and failure; provider discovery requires configured, allowed reads. |
| `/connectors` | Staff reads; bounded actions require their role and policy | `/connectors`, connector-specific reads and smart-action invocation; adapters and action service | Honest blocked, unconfigured, unavailable and failed states. Fixture coverage does not establish live-provider support. |
| `/integrations/connector-instances` | Administrator UI; M creation/configuration | `/secrets`, `/connector-instances`, mappings and instance sync; encrypted vault, tenant store, poller | Guided creation, duplicate-submit guard, error feedback and empty list. Saving now explicitly says provider access is unverified. Mapping confirmation is local operator confirmation. |
| `/operations/reconciliation` | Administrator UI; M remediation | `/ingestion/unmapped`, `/ingestion/quarantined`, mappings; quarantine/provenance store | Empty results, filters, confirmation dialogs, mapping/reclassification results and errors. No silent assignment to another client. |
| `/settings/access` | M only | `/auth/principals`, credentials, memberships, identities and OIDC config; identity/session store | Access-denied fallback before mounting admin controls, empty directory, saved changes and API errors. New credentials are shown only when issued. |
| `/settings` | A UI gate; individual operator APIs enforce M where required | Security/providers, vault, backups, updates, packs; local configuration and services | Gate, loading/error states, saved settings, unavailable update channel and optional integration states. Writes retain backend policy. |
| `/microsoft-admin/access` | A UI gate; capability administration backend checks | `/packs/microsoft-admin/access/*`; persisted capability grants | Checking/denied/list/empty/error states; environment bootstrap identity cannot manufacture a capability grant. |
| `/microsoft-admin` | Explicit Microsoft Admin capability and applicable role; exact client | `/packs/microsoft-admin/*`; scoped Graph connection and pack services | Access checking and denial precede mounting; result panels distinguish blocked/unconfigured/provider outcomes. No live Graph verification in this review. |
| `/microsoft-admin/azure-lighthouse` | Microsoft Admin capability plus endpoint role; scoped tenant | Lighthouse pack endpoints; credential profiles and Azure adapter | Lazy loading, configuration/access failure, read/onboarding result. Azure deployment is not inferred from a generated onboarding artifact. |
| `/m365-actions` | Scoped staff read access; drafts require T/A as action specifies | `/connectors/m365/*`, shared approval service | Empty provider choices, read errors, draft outcome and approval link. Drafting does not mean execution. |
| `/tickets` | V reads, T service actions; exact client | `/tickets`, ticket intelligence/context, drafts and support messages; ticket, evidence and approval store | Loading/empty/error, detail selection, bounded action response, requester replies versus internal notes. Provider retry/result remains explicit. |
| `/technician-chat` | T+; selected client | `/technician/chat/sessions`, message/close routes, smart-action runs; persisted sessions, evidence and plans | No-client notice, role denial, empty/new session, send errors and result plan. Switching clients now removes old conversations, drafts and late responses. |
| `/technician-path` | Staff guidance | Links into tickets, chat, approvals and audit | A navigation guide, not a second execution engine. |
| `/approvals` | V reads; T/A decisions and execution as required; exact client | `/approval-requests`, provider-specific execute routes; shared approval/policy/audit service | Empty/pending/approved/rejected/expired and execution outcomes. Approved content, expiry and write gates remain backend controlled. |
| `/activity/runs` | Staff scoped reads | `/packs/operator-control/activity/runs`; shared execution/activity projections | Loading, kind filters, empty results, failure, related execution/audit links. An activity row is not proof of provider success. |
| `/executions/:executionId` | Scoped authorized reader | `/executions/{id}` and artifact endpoints; canonical execution and evidence store | Detail loading, inaccessible/missing record error, persisted status, authorized artifact download. |
| `/audit` | Scoped reader; export requires A | Audit events and `/audit-events/export`; immutable operation evidence | Search/empty/error and local export; actor, approval and execution references retain client scope. |
| `/analytics` | Staff scoped read | `/analytics/summary`; execution, approval and ticket history | Loading/error/zero counts; time saved and model cost are explicitly estimates, not measured business outcomes. |
| `/workflows` | V reads, T runs; selected client | Templates, workflow runs, comparisons; workflow engine and store | Empty templates/runs, running/completed/failed states, inspected steps. Live tools still require policy/approval. |
| `/workflow-designer` | Staff; save requires action role | Workflow template gallery and templates; versioned local definitions | Editing/validation/save errors, saved definition. Saving a definition does not execute it. |
| `/templates` | Staff reads; mutations require action role | `/workflow-templates/gallery/*`; revisions, export/import and restore store | Empty gallery, revision/diff and export, save/import failure. Restore remains explicit. |
| `/playbooks` | Scoped staff; preview/run/mutation boundaries | `/msp/playbook-entries`, playbook previews/runs; shared services and revisions | Empty entries, preview result, validation errors and run outcome. Preview is distinct from execution. |
| `/integrations/smart-actions` | Staff catalog; invoke checks T/A and scope | `/smart-actions`, definitions, `/invoke`; deterministic action registry | Filtered/empty catalog, required inputs, blocked/failed/success action result. Catalog presence is not provider readiness. |
| `/agents` | Scoped staff; mutations/runs require action role | Agents, revisions, agent runs/backfills; bounded orchestration and policy | Definition/run loading, empty states, cancellation/retry/error. Model output cannot grant authorization. |
| `/agent-platform` | Optional pack and applicable role; scoped work | `/packs/agent-platform/*`; skills, memories, iterations and supervisor services | Optional/unavailable state, lists, iteration outcomes and errors. Enabling UI does not bypass shared tools or policy. |
| `/consultant` | Solutions architect, T+ for generation; selected client | `/consultant/discovery/sessions`, blueprints, architecture, governance/evaluations; consultant service and SQLite | Guided answers can be revisited; loading, validation failure, saved blueprint, assumptions and delivery handoff. Generated plans are not deployed solutions. |
| `/consultant/solution-delivery` | Architect/admin; exact client and deployment gates | Power Platform package/validate/materialize, deployment and rollback approvals; artifact builder and PAC adapter | Package preview/validation/download, explicit unsupported/missing CLI states, approval links. Import, deployment and verification are separate outcomes. |
| `/founder` | A; configured local project / explicit external handoff | `/founder/scan`, preview, upload, results, optional pack; sanitized bundle store and Launch Passport client | Project selection, local scan, fresh preview, explicit upload confirmation, unconfigured/failed handoff, optional-pack states. Source bodies and secret values are excluded. No live upload performed. |
| `/end-user` | Supported U identity; fixed requester/client | `/end-user/config`, tickets, messages and escalation; requester-scoped ticket store | Disabled identity/config state, input validation, empty requests, sent message and error. Existing identity boundary is tested; production multi-requester provisioning remains roadmap work. |
| `/collectors` | V reads, T local runs; explicit client | Modules, validate/preview/run, results/export; bounded collector registry | Empty runs, preview, confirmation, running/result/error and download. Collection scope distinguishes appliance/host data. |
| `/reports` | Scoped reads; A operational checks as indicated | Reports/export, hardening and restore exercises; report builders and local evidence | Empty/history/detail, generation failure, PDF/JSON/download outcomes. Report generation is not production certification. |
| `/system/appliance-health` | Operator; privileged backup actions checked separately | `/health`, update status, backups and hardening runs; local services/store | Readiness, unavailable checks, last result and action error. Health does not imply all provider integrations work. |
| `/system/diagnostics` | Authorized operator | `/diagnostics/summary`, bundle preview/download, pack status; redacting diagnostic service | Loading/empty correlation inventory, preview, failed download and local bundle. Review precedes export. |
| `/system/extensions` | Staff status; A install action | `/packs`, `/packs/status`, `/packs/install`; pack registry/license verification | Installed/locked/missing/unavailable and installation errors. Optional capabilities are not simulated. |
| `/integrations/mcp` | Staff catalog; invocation retains tool authorization | `/tools`, `/mcp`; shared tool registry | Published catalog, empty/error/status information. MCP is another entry to the same governed runtime. |
| Unknown routes | Any signed-in persona | SPA not-found component | Explicit not-found page and navigation back. |

Legacy routes are redirects, not separate workflows: `/automation/events`
maps to activity runs; `/automation/schedules` and `/scheduled-jobs` select
scheduled runs; `/backfills`, `/executions` and `/smart-actions/runs` select
their corresponding run kinds. Existing deep links retain their intent.

## Coverage anchors and tested boundaries

The backend suite covers the API/service side; the UI suite covers rendered
components with deterministic responses. Neither substitutes for the blocked
real-browser acceptance journeys.

| Journey | Existing coverage anchors | Coverage added here |
| --- | --- | --- |
| Sign-in, principals and client switching | `test_rbac.py`, `test_principals.py`, `test_auth_sessions_api.py`, `test_wla_p1_clients.py`; Login/DashboardContext/PrincipalsAdmin component tests | `test_per_client_roles.py`: bearer and session roles, forged body/header scope, approval denial, preserved directory, membership updates, conflicting and foreign scope. UI tests revoke stale permissions and clear prior-account selection. |
| Technician, approvals, audit, tenant isolation | `test_api_technician_chat.py`, `test_client_scope_enforcement.py`, `test_smart_actions.py`, `test_auth_boundaries.py`; TechnicianChat/Approvals/Tickets component tests | Chat remount regressions cover unsent state and delayed responses. New independent `tenant-and-role-isolation.spec.ts` journeys use unique local principals and real UI sign-in/chat/client switching; browser execution remains pending. |
| Connector setup and malformed input | ServiceNow/Syncro/Graph/provider API tests; ConnectorInstances component and production-readiness browser specification | No-provider-call guards for invalid filters and authentication failures; control-character regressions; saved-but-unverified notice and stronger browser assertion. |
| Architect and delivery | `test_api_consultant.py`, consultant/delivery/Power Platform tests; Consultant and SolutionDelivery component suites; consultant demo script | No provider capability expansion. Demo script and existing deterministic artifact/deployment-boundary coverage rerun. |
| Founder handoff | `test_founder_surface.py`, `test_lp_client.py`, `test_lp_polling.py`; Founder UI fixtures | Missing-token test now has a transport that fails if called. Existing preview, source/secret exclusion, stale preview, wrong project and failed upstream projection tests remain intact. |
| End-user support | `test_end_user_support.py`, API ticket tests, EndUserSupport component suite | Existing requester, client and internal-note boundaries rerun; production multi-requester identity was not added. |
| Appliance, migration and recovery | `test_store.py`, `test_spine_p0.py`, migration/provenance/backup tests, diagnostics and server-entry tests | Store lifecycle tests require released handles after reads, writes, rollback and setup failure. Local process smoke checks non-demo/demo startup, unauthenticated denial, port conflict, shutdown, restart and persisted data. |

## CLI, desktop and deployment map

The CLI exposes the same collectors, knowledge, agents, workflows, approvals,
consultant, founder, provider, diagnostics and backup services. CLI help and
the local-first and consultant scripts were executed. Their results establish
local/fixture behavior, not a provider tenant's readiness. The surface inventory
test checks the complete Typer command registry against its committed manifest.

The desktop shell launches the packaged API sidecar and displays this same UI.
Its startup/sign-in/navigation/reopen behavior could not be exercised without
Rust, the sidecar build requirements and a graphical runtime. Version alignment
was checked from the repository's release validator. Desktop is a local wrapper,
not a verified replacement for the MSP production appliance.

Development and production Compose wrappers were invoked but exited because
Docker is absent. A production-style source process was verified with disposable
credentials, a temporary vault/database and disabled writes/probing/inference.
Fresh and populated database, migration rollback/idempotence and backup/restore
fixtures remain the local database validation basis. No preceding-release image
upgrade or actual production volume restart was verified.

## Release limitations

Release assessment: **Not ready** for production sign-off from this review.
The changes repair reproduced defects, but real browser journeys, the four
requested viewport/accessibility passes, Compose/image integration and desktop
checks still require a suitable environment. There are no product screenshots
from this run. Unit/component results must not be described as visual QA.

Open PR #480 concerns a proposed artifact-generation roadmap and was not
implemented. Existing issues #257/#259 already track browser controls and broad
release-readiness verification; #554 tracks production multi-requester identity.
These are distinct from fixed defects and from unavailable provider credentials.
Live-provider and production verification remain unperformed by design.
