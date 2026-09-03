# WAIT Local Agent operator UI usability audit

Date: 2026-09-02  
Task: `wla-post60-t05`  
Branch baseline: `origin/main` at `5df1649b`

## Executive verdict

The operator UI has useful safety language and strong empty-state intent, but it
still asks the operator to assemble the product model from many overlapping
surfaces. The highest-risk experience is the core path from a selected client to
a governed action: the shell selector, screen-level selectors, connector setup,
playbook/action catalog, approval queue, activity history, and audit are separate
places with different names and prerequisites. Demo mode makes this worse because
the UI derives write affordances from role while the appliance rejects writes.

The first phase-2 work should make scope and capability state authoritative in
the shell, then make the action-to-approval-to-result path one understandable
journey. The audit found one route served outside the route manifest, one hard-coded
operator-facing status, one transient handoff, and several areas where empty or
permission states are technically accurate but arrive too late to guide the
next action.

## Method and evidence boundary

The requested order was followed:

1. `scripts/demo_appliance.sh` was attempted. It stopped because
   `wait-local-agent` is not installed on `PATH`.
2. The repository fallback, `UV_CACHE_DIR=/tmp/wla-post60-t05-uv-cache uv run
   wait-local-agent doctor`, was attempted. It could not create a runnable
   environment because the sandbox cannot resolve `files.pythonhosted.org` and
   could not download `grpcio==1.82.1` / `opentelemetry-semantic-conventions==0.65b0`.
3. `cd ui && npm ci` completed from the lockfile. `npm run dev -- --host
   127.0.0.1` started Vite 8.2.2, but no API appliance was available behind it.
   The Playwright wrapper was attempted; its `npx` package bootstrap did not
   complete in the network-restricted sandbox. No route screenshot is therefore
   presented as rendered evidence.
4. Every concrete route in `ui/src/routes.tsx`, the wildcard route, the shell,
   and the relevant screen tests were statically reviewed. Every row below is
   explicitly marked `static review only`; no runtime state, visual layout, or
   click result is inferred from an unrendered screen.

The static review used the route manifest at `ui/src/routes.tsx:142-208`, shell
components at `ui/src/app/AppShell.tsx:20-73`,
`ui/src/app/Sidebar.tsx:42-160`, and `ui/src/app/ActivityShell.tsx:3-65`, plus
each screen's implementation and nearby tests. No screenshots were captured
because the appliance could not be started.

## Review criteria

`Purpose` and `Action` use yes / no / unclear: yes means the screen states its
job and presents a recognizable next action; unclear means the page has several
competing actions or only exposes the purpose after prerequisites are met.
`Dead-end / prerequisite` records disabled controls, missing setup, error or
empty-state guidance. `Jargon / literals` lists literal operator-facing terms
that may need plainer copy, and hard-coded status values where relevant.

## Screen-by-screen inventory

| Route | Purpose / primary action | Dead-end, prerequisite, empty or error guidance | Jargon, duplicate path, or hard-coded literal | Evidence and mode |
| --- | --- | --- | --- | --- |
| `/login` | Purpose yes: sign into the appliance. Action yes: `Sign in`; Microsoft sign-in is a conditional second action. | Requires an access token unless OIDC is enabled. Rejected-token and OIDC failure copy is actionable. | `Access token`, `Microsoft 365`, `OIDC` is present in behavior/source, though OIDC is not explained on the screen. | `ui/src/screens/Login.tsx:79-116`; static review only |
| `/` | Purpose yes: `Operations Overview`. Action unclear: four cards, onboarding, and three no-ticket links compete. | Onboarding can appear as a modal; empty workflow/event/retry lists say only `No ... visible`, with no route-specific recovery. | `demo-ready`, `Writes gated`, `Safe Mode` and scope badge. | `ui/src/screens/Overview.tsx:90-144,149-187`; static review only |
| `/clients` | Purpose yes: client directory. Action yes for `New client` / selecting a client. | Creating/editing is administrator-only; empty state points to a CLI seed command rather than the UI. Details exist only after selecting a row. | `Client ID`, `Commercial`, `environment entities`, `baseline`, `drift`; client selection duplicates the shell selector. | `ui/src/screens/Clients.tsx:440-478,513-530`; static review only |
| `/client-discovery` | Purpose yes: review provider organizations. Action yes: `Run discovery`, accept/create/dismiss. | Requires administrator access, MSP mode, and an active PSA; SMB mode intentionally disables the journey. Empty copy names the missing PSA. | `PSA`, `provider organization`, `match state`, `reconcile`; discovery duplicates manual client creation. | `ui/src/screens/ClientDiscovery.tsx:134-144`; static review only |
| `/connectors` | Purpose yes: connector readiness and readout. Action unclear: refresh, explorer reads, and multiple provider-specific approval forms. | Setup is exposed in expandable details and may redirect to Connector Instances; provider configuration is not a single guided setup flow. | `HTTP probing`, `write actions`, `PSA`, environment variable names; screen-level client selectors duplicate the top bar. | `ui/src/screens/Connectors.tsx:234-260,280-327,351-416`; static review only |
| `/m365-actions` | Purpose yes: Microsoft 365 action drafts. Action yes after selecting a catalog action: `Create approval draft`. | Administrator-only; requires a selected client and the relevant lookups/provider capability. Disabled submit does not itself state the missing client. | `M365`, `Entra`, `approval draft`, `lookup`; overlaps Microsoft Administrator and Smart Action catalog. | `ui/src/screens/M365Actions.tsx:409-451`; static review only |
| `/microsoft-admin` | Purpose yes: correlate Microsoft evidence and prepare governed runbook drafts. Action unclear until evidence and remediation sections load. | Requires the Microsoft Admin capability and technician/admin access for runbooks; empty remediation copy says only that the pack has none. | `Intune`, `Defender`, `PowerShell`, `risk level`, `source readiness`; overlaps M365 Actions. | `ui/src/screens/MicrosoftAdmin.tsx:544-555,603-650,730-811`; static review only |
| `/microsoft-admin/azure-lighthouse` | Purpose yes: delegated subscription discovery and onboarding package. Action yes when connection is ready. | Requires capability, connection readiness, inventory, and customer tenant data. Empty subscription/resource messages are clear but do not link to the prerequisite setup. | `Azure Lighthouse`, `delegated subscription`, `tenant`, `ZIP`; specialist jargon is not translated. | `ui/src/screens/AzureLighthouse.tsx:182-218,267-350,368-421`; static review only |
| `/microsoft-admin/access` | Purpose yes: grant or revoke Microsoft Admin capability. Action yes. | Requires an existing principal and eligible client role; empty states explain both missing objects. | `principal`, `global scope`, `MSP admin`, `capability grant`; overlaps the two People & Access screens. | `ui/src/screens/MicrosoftAdminAccess.tsx:155-249`; static review only |
| `/settings/access` | Purpose yes: People & Access. Action yes: create identity, issue/revoke credential, manage roles. | MSP administrator-only. Role and credential prerequisites are present but spread across panels. | Literal `bearer credentials`, `Microsoft Entra`, `principal`; duplicate people path with `/system/identity-access`. | `ui/src/screens/PrincipalsAdmin.tsx:252-280,299-372`; static review only |
| `/knowledge` | Purpose yes: ingest and search tenant knowledge. Action yes after client/path selection. | Ingest requires write access, selected client, and a path; search and authority editing have different scopes. Empty guidance is split between controls and results. | `OCR`, `parser`, `authority`, `SOP`, `client ID`; screen-level selector duplicates the shell. | `ui/src/screens/Knowledge.tsx:138-167,194-216`; static review only |
| `/workflows` | Purpose yes: run a reviewed workflow template. Action yes: choose template/ticket and run. | Requires template, ticket, write access; empty runs link back to the form. History is separate from canonical Activity. | `workflow template`, `approval`; automation shell calls this tab `Run`, which is helpful but not visible in the main sidebar label. | `ui/src/screens/Workflows.tsx:115-188`; static review only |
| `/automation/events` | Purpose yes: event delivery history and test emission. Action yes for `Emit test event` / retry. | Event shape/subscription prerequisites are not obvious before the form; retry feedback is available after action. | `delivery`, `subscription`, `event type`; activity navigation is a second taxonomy. | `ui/src/screens/Events.tsx:136-198,274-343`; static review only |
| `/automation/schedules` | Purpose yes: scheduled automation view. Action unclear: this is mostly a list, while creation lives in Scheduled Jobs. | Empty and filtered-empty states are explicit; the create path is not a primary action here. | `scheduled job`, `cron`, provider status; overlaps `/scheduled-jobs`. | `ui/src/screens/Schedules.tsx:45-107,147-194`; static review only |
| `/activity/runs` | Purpose yes: unified run history. Action yes: filter/refresh and open a run. | Empty state names current tenant and filters but does not link to the producing surfaces. | `tenant-scoped`, `legacy workflow`, `backfill`; seven activity tabs create competing result locations. | `ui/src/screens/ActivityRuns.tsx:65-81`; static review only |
| `/workflow-designer` | Purpose yes: design-only graph. Action yes after client/template selection. | Explicitly does not run workflows; create/save buttons need technician access, client, and reviewed template. Disabled controls rely on title text. | `trigger`, `acyclic graph`, `bounded palette`; “Designer” and “Run” are adjacent but execution wiring is intentionally absent. | `ui/src/screens/WorkflowDesigner.tsx:203-279`; static review only |
| `/templates` | Purpose yes: create/edit tenant copies. Action yes: create local template. | Requires a reviewed source template and write access; run requires enabled copy. Empty state links to the form. | `tenant-scoped`, `revision`, `import/export`; “My templates” is distinct from Playbooks and Workflows. | `ui/src/screens/Templates.tsx:215-263`; static review only |
| `/playbooks` | Purpose yes: publish, preview, and run multi-step playbooks. Action yes after client selection. | Screen explicitly says to select a client; publish/edit/run also require write access and enabled copy. Empty subscription state is informative. | `MSP`, `connector requirements`, `tenant copy`; overlaps workflow/template execution. | `ui/src/screens/Playbooks.tsx:456-518,675-721`; static review only |
| `/consultant` | Purpose yes: Solutions Architect discovery, blueprints, evaluation, and artifact handoff. Action unclear because six groups and independent builders coexist. | Several operations require client, blueprint, evidence, or ticket; controlled execution is demo + Safe Mode only. Section-specific errors can be easy to miss. | `Power Apps`, `Dataverse`, `Power Automate`, `Copilot Studio`, `governance`, `deployable`, `execution started`; screen-level client selection and implicit fallback resolution. | `ui/src/screens/Consultant.tsx:840-921,990-1010,1360-1373,1424-1507`; static review only |
| `/consultant/solution-delivery` | Purpose yes: package, validate, materialize, and request deployment/rollback approval. Action yes in a numbered pipeline. | Requires client/package and backend gates; the handoff arrives through transient router state and is cleared on mount. | `PAC`, `WAIT_ALLOW_*`, `materialize`, `ZIP`, `deployment_started`; literal validation detail includes `deployable: true`. | `ui/src/screens/SolutionDelivery.tsx:132-158,412-531`; static review only |
| `/collectors` | Purpose yes: inspect local collectors. Action yes: choose, check, run, export. | Empty states link back to the collector form. Host/container scope is explained but still requires operator interpretation. | `collector`, `host`, `container`, `network sockets`, `SQLite`; screen-level client selector is unnecessary for some local collectors. | `ui/src/screens/Collectors.tsx:197-204,283-307,350-368`; static review only |
| `/reports` | Purpose yes: evidence and client reports. Action unclear: run checks, drill restore, generate three report types, filter, open, and export. | Admin-only actions are explained; report empty state is generic. Report generation does not visibly require a client until submission behavior. | `QBR`, `automation-opportunity`, `restore drill`, `PDF`, `client scope (admin only; others are bound)`; screen-level selector duplicates shell. | `ui/src/screens/Reports.tsx:224-340,429-461`; static review only |
| `/audit` | Purpose yes: local audit history/export. Action yes: filter and export. | Empty state is useful only after filters; it does not link back to Activity or the action that creates evidence. | `audit`, event types, correlation identifiers; overlaps Activity and execution details. | `ui/src/screens/Audit.tsx:73-110`; static review only |
| `/scheduled-jobs` | Purpose yes: create and inspect schedules. Action yes, but required fields change by schedule type. | Workflow/playbook/agent/report/graph-sync/backup prerequisites are conditional; no single checklist explains them before selection. | `cron`, `graph sync`, `MSP playbook`, `entity ID`; duplicate schedule view with `/automation/schedules`. | `ui/src/screens/ScheduledJobs.tsx:141-220,260-286`; static review only |
| `/founder` | Purpose yes: five-step Launch Passport scan/upload journey. Action yes: choose folder, review, confirm, launch, results. | Founder Pack, connection, credits, role, and project state can send the user backward; copy does explain most recovery destinations. | `Launch Passport`, `credits`, `vault`, `artifact`; payment/pack terms are mixed into a product journey. | `ui/src/surfaces/founder/FounderJourney.tsx:15-25,80-123,347-421`; static review only |
| `/tickets` | Purpose yes: ticket workspace and local action drafts. Action yes after selecting a ticket. | Requires a visible ticket and often a client/provider; empty demo guidance points to a CLI seed. Context/actions/notes are tabs rather than a guided path. | `PSA`, `HaloPSA`, `approval drafts`, `requester`; global selector controls the scope while ticket selection is local. | `ui/src/screens/Tickets.tsx:331-378`; static review only |
| `/approvals` | Purpose yes: approval queue. Action yes: approve/reject/execute where allowed. | Some actions require admin, write health, or a client; the final external result is not on this screen. Empty state is a plain `No approval requests yet.` | `approval`, `write gate`, `PowerShell`; result continues to Activity/Audit. | `ui/src/screens/Approvals.tsx:83-122`; static review only |
| `/analytics` | Purpose yes: scoped operational metrics. Action yes: filter/apply. | Empty metric derivations are honest but repetitive; filter scope and global scope can be confused. | `model cost`, `tokens`, `tenant scope`, `derivation`; screen-level selector duplicates shell. | `ui/src/screens/Analytics.tsx:109-164,186-196`; static review only |
| `/agents` | Purpose yes: create/review/run bounded agents. Action unclear: large form, revision history, run controls, and plan preview. | Requires tools, client mapping in some cases, write access, and ticket IDs. Empty state has a useful anchor. | `JSON objects`, `Smart Actions`, `revision`, `result-aware`; screen-level selector duplicates shell. | `ui/src/screens/Agents.tsx:384-448,485-545`; static review only |
| `/agent-platform` | Purpose unclear: five tools in one tabbed platform. Actions vary by tab: store, create, continue, rank, upload/analyze. | Each tab has its own prerequisites and disabled actions; users must discover that tabs are independent. Empty guidance is generally specific. | `scope ID`, `provenance`, `SHA-256`, `Smart Action`, `iteration session`; high jargon and no one primary journey. | `ui/src/screens/AgentPlatform.tsx:183-190,270-292,382-406,493-517,695-748`; static review only |
| `/technician-chat` | Purpose yes: bounded technician chat. Action yes after client selection and technician access. | Explicit read-only fallback and “Select a client from the top bar” guidance are good; session/history and notification approval are separate branches. | `smart-action catalog`, `tenant-scoped`, `approval-gated`; client selector is duplicated locally. | `ui/src/screens/TechnicianChat.tsx:197-231,251-259`; static review only |
| `/technician-path` | Purpose yes: five-step technician journey. Action yes: each step has `Open`. | Links are clear, but Plan and Triage both open Chat; no persistent progress or handoff state. | `approval`, `local evidence`; this is a duplicate navigation path for Tickets → Chat → Approvals → Audit. | `ui/src/screens/TechnicianPath.tsx:3-30`; static review only |
| `/backfills` | Purpose yes: preview/queue/control historical agent runs. Action yes after choosing agent/scope. | Requires write access and often a client; terminal/failed button titles explain disabled actions. Empty state links to the form. | `backfill`, `rerun-failed`, `terminal`; overlaps Agent Platform iteration/history. | `ui/src/screens/Backfills.tsx:125-154`; static review only |
| `/executions` | Purpose yes: canonical execution history and detail. Action yes: select run/download artifact. | Empty state explains when records appear; no direct link from an approval to the matching execution is documented on screen. | `execution record`, `artifact`, `media type`, `SHA-256`; overlaps Activity Runs and Smart Action Runs. | `ui/src/screens/Executions.tsx:69-103`; static review only |
| `/settings` | Purpose yes: administrator settings. Action unclear: status, onboarding, updates, Launch Passport, licensing, packs, backups, vault. | Admin-only gate is clear; demo mode says restart is required, but many settings are read-only status rather than controls. | Literal `API token`, `remote model`, `USD per million tokens`, `WAIT_DEMO_MODE`, `vault`; raw infrastructure/auth/billing vocabulary. | `ui/src/screens/Settings.tsx:196-220,295-340,368-499`; static review only |
| `/system/appliance-health` | Purpose yes: read-only appliance health and backup. Action yes: refresh or run backup when enabled. | Admin-only; backup is disabled in demo mode and the first count slot can show the literal `admin only` instead of a count. | `demo_mode`, `secrets backend`, `hardening`; hard-coded `admin only` is misleading in a count position. | `ui/src/screens/ApplianceHealth.tsx:112-130,153-229`; static review only |
| `/system/diagnostics` | Purpose yes: safe local diagnostics/support bundle. Action yes: refresh/generate/download. | Admin-only; support upload is clearly unavailable and download remains available. | `database integrity`, `build`, `redacted`, `correlation`; “database” is operator-visible jargon. | `ui/src/screens/DiagnosticsSupport.tsx:106-119,137-221`; static review only |
| `/system/extensions` | Purpose yes: install/list packs. Action yes: install pack. | Admin-only; empty state says no packs but does not say where a valid pack comes from. | `pack`, `signature`, `license`; install is a high-impact action with minimal preflight guidance. | `ui/src/screens/ExtensionsPacks.tsx:112-165`; static review only |
| `/system/identity-access` | Purpose yes: create principals and credentials. Action yes. | MSP administrator-only; empty state says `No database principals`, which is implementation language. | `database principals`, `bearer`, `MSP administrator`; duplicate people path with `/settings/access`. | `ui/src/screens/IdentityAccess.tsx:168-211,224-286`; static review only |
| `/integrations/mcp` | Purpose yes: MCP connection details/tool catalog. Action yes: copy details; no in-app connect action. | Admin-only; empty catalog says no tools but does not link to enabling/publishing them. | `MCP`, `bearer token`, `tool catalog`, `approval flag`; developer-facing terms on an operator surface. | `ui/src/screens/McpIntegration.tsx:158-233,250-255`; static review only |
| `/integrations/connector-instances` | Purpose yes: connect systems and map external companies. Action yes, but the form is long. | Admin-only; requires provider credentials, vault storage, client mapping, and verification. “Try again” covers load errors but not setup sequence. | `vault`, `Base URL`, `tenant`, `external company`, `verification`; hidden behind System / Advanced in the sidebar. | `ui/src/screens/ConnectorInstances.tsx:602-631,844-966,1003-1111`; static review only |
| `/integrations/smart-actions` | Purpose yes: inspect bounded action catalog. Action unclear: select action to see detail; no obvious route into an execution. | Empty catalog state is available; action detail points toward use by other surfaces rather than a next step. | `risk level`, `approval required`, `Smart Action`; overlaps M365 Actions, Agents, Chat, and Connector Explorer. | `ui/src/screens/SmartActionCatalog.tsx:78-102,245-255`; static review only |
| `/smart-actions/runs` | Purpose yes: individual smart-action run history/detail. Action yes: filter/select. | Empty/history and detail states are separate; no direct “open approval” or “open audit evidence” handoff is evident. | `Smart Action Run`, action IDs, payload/output; overlaps unified Activity and Executions. | `ui/src/screens/SmartActionRuns.tsx:142-155`; static review only |
| `/operations/reconciliation` | Purpose yes: sync health, quarantine, mappings, and quarantined tickets. Action unclear: many admin actions across sections. | Requires admin, connector state, mappings, and verification; “quarantine/unmapped” requires domain knowledge. | `reconciliation`, `quarantine`, `unmapped`, `ingestion`; high operational jargon and duplicate connector mapping locations. | `ui/src/screens/SyncReconciliation.tsx:237-254,285-327,399-467`; static review only |
| `/*` (manifest wildcard `*`) | Purpose yes: recover from an unknown path. Action yes: `Return to Overview`. | Copy includes the attempted path and a single recovery link. | `Page not found`; no navigation to the likely intended route. | `ui/src/screens/NotFound.tsx:4-14`; static review only |

### Repeated shell observations

- The top bar always presents `Client`, `Refresh`, account/auth state, sign-out,
  and write posture (`ui/src/app/AppShell.tsx:20-73`). That is a useful global
  frame, but it is not the only scope control.
- `ClientIdSelect` is independently controlled by each screen
  (`ui/src/components/ClientIdSelect.tsx:3-31`). The shared test enumerates 13
  screen-level uses (`ui/src/screens/ClientIdSelectScreens.test.tsx:93-111`),
  while Activity, Audit, Executions, and Overview use the global scope badge.
- Sidebar navigation puts several core surfaces in primary groups but hides
  connector instances, identity, settings, reconciliation, appliance health,
  diagnostics, packs, and MCP under `System / Advanced`
  (`ui/src/app/Sidebar.tsx:74-116,139-160`). It also renders `/end-user`, which
  is not in the route manifest (`ui/src/app/Sidebar.tsx:54-59`,
  `ui/src/routes.tsx:143-203`); the link works because `ui/src/App.tsx:10-11`
  mounts `EndUserSupport` before `AppRoutes`, but the path is therefore outside
  the manifest that `tests/test_static_ui.py:175-193` enforces and outside the
  backend's content-negotiated deep-link list.
- Activity has seven tabs with overlapping histories
  (`ui/src/app/ActivityShell.tsx:3-31`), while Audit, Executions, and
  Smart Action Runs remain separate routes. This makes “where did my result
  go?” a recurring operator question.
- Status chips humanize many server statuses (`ui/src/components/StatusChip.tsx:7-43`),
  but screens still expose literal infrastructure/status values such as
  `admin only`, `deployable: true`, `execution_started: false`, and
  `deployment_started: false` (`ui/src/screens/ApplianceHealth.tsx:202-229`,
  `ui/src/screens/SolutionDelivery.tsx:455-486`).

## Core-journey narratives

### 1. Sign in → client → connector → action/playbook → approval → result

The sign-in entry point is understandable: the user sees `Sign in to the
appliance`, an access-token field, and an optional Microsoft button. After
entry, the shell exposes a global client selector. The next meaningful step is
not equally discoverable: `/connectors` is a readiness/readout page, while the
actual per-client setup form is `/integrations/connector-instances`, hidden in
System / Advanced. Once connected, the operator must create and verify an
external-company mapping before provider-scoped behavior is trustworthy.

The operator then chooses among Workflows, Playbooks, M365 Actions, Smart
Actions, Agents, or Technician Chat. Playbooks clearly warn that a client is
required, but many other surfaces use their own `ClientIdSelect`; a selection
made in a local form can disagree with the top-bar scope. In demo mode the
shell says `Demo mode` and the help copy says writes are unavailable, yet
`canWrite` is derived as `roleResolved && role !== "viewer"`
(`ui/src/app/DashboardContext.tsx:596-603`). The write buttons consume that
role-only value, so the operator can reach an enabled-looking action and only
learn at the API boundary that demo writes are refused.

Approval is a separate queue with its own role/write-health rules. After
approval, the result is not a single continuation: it may be in Activity Runs,
Executions, Smart Action Runs, Workflow history, or Audit. The UI has accurate
individual descriptions, but no consistent “approved → execution → evidence”
handoff. This is an S1/S2 combination: the safety boundary is preserved, while
the operator journey is easy to abandon or misread.

### 2. Solutions Architect → Solution Delivery

The Solutions Architect page contains discovery, blueprint selection,
Power Apps, governance/evaluation, employee-onboarding walkthrough, and a
handoff panel. The handoff panel says artifacts are ready and links to Solution
delivery (`ui/src/screens/Consultant.tsx:1360-1373`). Solution Delivery receives
those artifacts through `location.state`, immediately replaces the route state
with `null`, and seeds an in-memory package form
(`ui/src/screens/SolutionDelivery.tsx:132-158`). This makes the first transition
work conceptually, but the handoff is not durable across refresh/navigation and
the receiving page does not show a persistent source blueprint identity.

The delivery page's numbered pipeline is a good mental model: package, validate,
materialize, deployment approval, rollback approval. It also correctly exposes
backend gates. The remaining comprehension problem is that review-only package
status and deployment state are expressed with implementation literals, while
the user is deciding whether a solution is ready for delivery. The handoff
should preserve artifact identity and explain “review package” versus “approved
deployment” in one shared status model.

## Ranked findings

Severity: S1 blocks a core journey; S2 causes wrong understanding or a wasted
action; S3 is recurring friction; S4 is polish. Frequency is core journey,
weekly, or rare.

| Rank | Severity | Frequency | Screen / journey | Literal evidence | Finding and consequence |
| --- | --- | --- | --- | --- | --- |
| 1 | S1 | Core journey | Demo action surfaces | `canWrite: roleResolved && role !== "viewer"` — `ui/src/app/DashboardContext.tsx:601`; `Demo mode` — `ui/src/app/AppShell.tsx:179-185`; write buttons use `disabled={!canWrite}` — `ui/src/screens/Playbooks.tsx:510-518` | Demo users with a non-viewer role see write affordances despite the demo write boundary. They waste an action and may conclude the safety model is broken. |
| 2 | S1 | Core journey | Shell, client-scoped screens | `Client` selector — `ui/src/app/AppShell.tsx:31-43`; `ClientIdSelect` owns a separate value — `ui/src/components/ClientIdSelect.tsx:20-31`; 13 uses — `ui/src/screens/ClientIdSelectScreens.test.tsx:93-111` | Two scope mechanisms make it possible to prepare or inspect an action under a different client than the shell badge suggests. |
| 3 | S2 | Core journey | Sidebar / connector setup | `/integrations/connector-instances` is Advanced — `ui/src/app/Sidebar.tsx:96-103`; `/connectors` links to it as an alternate setup path — `ui/src/screens/Connectors.tsx:247-260` | The visible Connectors destination reads as readiness, but the actual setup path is hidden and split by appliance-wide versus per-client configuration. |
| 4 | S2 | Core journey | Approvals → Activity/Audit | Seven activity destinations — `ui/src/app/ActivityShell.tsx:3-31`; separate routes — `ui/src/routes.tsx:170-182,191-202`; Audit is a separate screen — `ui/src/screens/Audit.tsx:73-110` | Operators must guess whether “result” means workflow history, execution, Smart Action run, Activity, or Audit. |
| 5 | S4 | Rare | Sidebar / route manifest | Sidebar renders `to: "/end-user"` — `ui/src/app/Sidebar.tsx:54-59`; served by `ui/src/App.tsx:10-11` outside `AppRoutes` — `ui/src/routes.tsx:143-203` | Not a dead link (verified: `App.tsx` mounts `EndUserSupport` first), but the path is invisible to the route manifest and to the backend deep-link list, so manifest-based checks and the SPA content negotiation do not cover it. |
| 6 | S2 | Weekly | Consultant → Solution Delivery | Handoff is read from `location.state` and then cleared — `ui/src/screens/SolutionDelivery.tsx:132-158` | A refresh or later return loses the handoff context; the delivery operator cannot reliably identify which blueprint produced the package. |
| 7 | S2 | Weekly | Solution Delivery | `deployable: true · execution_started: false · deployment_started: false` — `ui/src/screens/SolutionDelivery.tsx:455-459` | Implementation vocabulary and a hard-coded “deployable” value can be read as a real delivery verdict, even though the page is still review-only. |
| 8 | S2 | Weekly | Appliance Health | `backupStatus?.total ?? "admin only"` — `ui/src/screens/ApplianceHealth.tsx:202-205` | A permission/loading fallback appears in a numeric count position, making the health summary look like a status value. |
| 9 | S2 | Weekly | Settings / Identity | `No database principals` — `ui/src/screens/IdentityAccess.tsx:210-211`; `API token`, `USD per million tokens`, `WAIT_DEMO_MODE` — `ui/src/screens/Settings.tsx:196-220,295-340` | Admin/support screens expose implementation, auth, and cost terms without consistently translating them into operator language. |
| 10 | S3 | Weekly | Automations | Run, Playbooks, My templates, Designer, and Action catalog are separate tabs — `ui/src/app/AutomationsShell.tsx:3-31` | The same underlying job is described as a workflow, template, playbook, agent, or Smart Action; users must know the data model to choose a starting point. |
| 11 | S3 | Weekly | Consultant | `Power Apps builder` says it is independent of the selected blueprint — `ui/src/screens/Consultant.tsx:1187-1195` | The page visually groups tools under Solutions Architect while explicitly saying one builder is independent, increasing the chance of an accidental disconnected artifact. |
| 12 | S3 | Weekly | Empty/error states | `No workflow runs visible`, `No event history visible`, `No reports available` — `ui/src/screens/Overview.tsx:149-187`, `ui/src/screens/Reports.tsx:339-340` | Many states report absence accurately but do not provide a next route or explain whether the cause is no data, no scope, no connector, or a failed request. |
| 13 | S3 | Rare | Extensions / MCP | `No packs are installed on this appliance` — `ui/src/screens/ExtensionsPacks.tsx:123`; `No tools are currently published to the catalog` — `ui/src/screens/McpIntegration.tsx:221` | High-impact setup surfaces stop at inventory and do not link to the valid source/configuration step. |
| 14 | S4 | Weekly | Activity naming | `All Runs`, `Executions`, `Smart Action Runs`, `Scheduled Jobs`, and `Backfills` — `ui/src/app/ActivityShell.tsx:3-31` | Naming and capitalization are inconsistent across adjacent history surfaces, slowing scanning and support conversations. |

## Phase-2 fix grouping

This is a prioritization proposal, not implementation work.

### Shell/navigation + client selector

Covers findings 2, 3, 4, 5, 10, and 14. Involves
`ui/src/app/AppShell.tsx`, `ui/src/app/Sidebar.tsx`,
`ui/src/app/ActivityShell.tsx`, `ui/src/app/AutomationsShell.tsx`,
`ui/src/components/ClientIdSelect.tsx`, `ui/src/components/ScopeBadge.tsx`,
and the route manifest. Target behavior: one authoritative client scope is
visible in the shell, every scoped surface consumes it or clearly declares an
intentional override, and the navigation exposes one obvious path for setup,
action, approval, result, and evidence. Register `/end-user` in the route
manifest (or document why it is mounted outside it) as part of the navigation
work.

### Connectors/setup

Covers findings 2, 3, and 12. Involves `Connectors.tsx`,
`ConnectorInstances.tsx`, `ClientDiscovery.tsx`, client detail mapping in
`Clients.tsx`, and setup/onboarding surfaces. Target behavior: Connectors tells
the operator whether to configure appliance-wide access or a client instance,
then links directly to the next missing prerequisite (credentials, client,
mapping, verification). A single setup checklist should distinguish read
access, approval drafting, and live write readiness.

### Approvals/activity

Covers findings 1, 4, 8, 12, and 14. Involves `DashboardContext.tsx`,
`Approvals.tsx`, `ActivityShell.tsx`, `ActivityRuns.tsx`, `Executions.tsx`,
`SmartActionRuns.tsx`, `Audit.tsx`, and shared status components. Target
behavior: the same server-derived capability/write state controls affordances
and copy in demo and live modes; every approval displays its resulting run and
evidence links; history labels explain whether a record is a workflow, action,
execution, or audit event without making the operator choose among duplicate
destinations.

### Solutions Architect / Solution Delivery

Covers findings 6, 7, 10, and 11. Involves `Consultant.tsx`,
`SolutionDelivery.tsx`, shared artifact/result models, and handoff tests. Target
behavior: a handoff is durable, names its source blueprint and artifacts, and
uses one plain-language lifecycle such as Draft → Reviewed → Approval needed →
Materialized → Deployed. Review-only and deployable states must be data-derived;
implementation keys remain in expandable technical details.

### Settings/people

Covers findings 5, 8, 9, and 13. Involves `Settings.tsx`, `ApplianceHealth.tsx`,
`DiagnosticsSupport.tsx`, `ExtensionsPacks.tsx`, `IdentityAccess.tsx`,
`PrincipalsAdmin.tsx`, `MicrosoftAdminAccess.tsx`, and `McpIntegration.tsx`.
Target behavior: consolidate People & Access, explain the difference between
an operator account, client role, capability, and credential, and give every
admin-only empty state a direct next step. Keep secrets and technical detail
redacted, but translate database/auth/billing vocabulary on the operator path.

## Validation notes for the audit artifact

- No files under `ui/src` or `src` were changed.
- No screenshots are included because no appliance-backed screen was rendered.
- The route-completeness check for this document is recorded in the task
  `implementation.md` with its output.
- There were no dependency or API changes in this audit. The existing locked UI
  dependencies were installed as-is; Vite reported 8.2.2 from the compatible
  lockfile. No version update is proposed.
