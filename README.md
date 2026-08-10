# WAIT Local Agent

[![CI](https://github.com/W-A-I-T/wait-local-agent/actions/workflows/test.yml/badge.svg)](https://github.com/W-A-I-T/wait-local-agent/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/W-A-I-T/wait-local-agent)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)

**Local-first MSP and founder automation appliance for tickets, runbooks, approvals, connector drafts, scheduled workflows, and auditable local operations.**

See the [capability roadmap](ROADMAP.md) and [NeoAgent parity matrix](docs/neoagent-parity-matrix.md) for the honest status of local-first MSP capabilities and the rationale for deferred work.

WAIT Local Agent is an Apache 2.0 self-hosted runtime with a FastAPI API, Typer CLI, React dashboard, SQLite state, signed update checks, and an open-core pack loader. The public repository ships the appliance surface; paid or proprietary pack implementation stays outside this repo.

> Safety default: fresh installs are read-first and local-first. Live connector writes require `WAIT_ALLOW_WRITE_ACTIONS=true`, outbound connector connection checks must be explicitly enabled, and HaloPSA writes still require an approved draft.

## What Ships In 1.1.1

- FastAPI API on port `8788`, React dashboard on port `5173`, and `wait-local-agent` CLI.
- Role-based bearer tokens with `WAIT_ADMIN_TOKEN`, `WAIT_TECH_TOKEN`, `WAIT_VIEWER_TOKEN`, plus legacy `WAIT_API_TOKEN` as an admin-equivalent token.
- Demo mode: when `WAIT_DEMO_MODE=true` and no role token is enforced, local demo flows run without bearer auth.
- SQLite-backed tickets, approvals, workflow runs, audit events, knowledge documents, and scheduled jobs.
- Client tenancy filters on stored surfaces such as `/tickets`, `/approval-requests`, `/audit`, `/audit-events/export`, `/workflow-runs`, `/knowledge/documents`, and `/scheduled-jobs`.
- HaloPSA read paths, approval-gated write drafts, and execution history.
- ConnectWise PSA ticket and company lookup plus an allowlisted,
  approval-gated ticket update path with explicit HTTP probing opt-in.
- Syncro ticket and customer lookup, bounded ticket-comment history, and one
  approval-gated, tenant-scoped ticket-comment action (`syncro-ticket-add-note`)
  with explicit HTTP probing and write-action opt-ins. The public contract is
  limited to documented comment fields; broader Syncro mutations remain
  unavailable.
- ServiceNow incident reads plus approval-gated work-note, state, assignment, and resolution-metadata updates, and
  Autotask ticket reads plus approval-gated ticket-note, status, and resolution actions, are
  available through the same bounded connector and agent-tool surfaces;
  broader mutations remain unavailable.
- Hudu read-only documentation context.
- A preview and approval-gated communication tool for local ticket notes,
  email, Microsoft Teams, Slack, and SMS. Local notes stay tenant-scoped;
  external delivery requires explicit SMTP/webhook configuration and both
  `WAIT_ALLOW_WRITE_ACTIONS=true` and `WAIT_ALLOW_HTTP_PROBING=true`.
- Connector credential validation with `wait-local-agent connectors validate halopsa`, `hudu`, `connectwise`, or `syncro`.
- Encrypted backup and restore with `wait-local-agent backup create --encrypt` and `wait-local-agent backup restore --encrypted`.
- Scheduled workflow and ticket-agent APIs under `/scheduled-jobs`, including
  UTC cron, interval, and future one-time schedules plus pause, resume,
  tenant-scoped reschedule, cancel/delete, linked ticket or agent targets, and
  auditable schedule history.
- Bounded agent definitions under `/agents`, an existing-tool catalog under
  `/tools` including read-only local knowledge search, ticket-quality,
  explicit-threshold SLA-risk and stale-ticket checks, deterministic
  sentiment/escalation checks, collector previews, a
  technician-gated Microsoft 365 identity lookup over collected read-only
  inventory plus a separate bounded live Graph user/group/license/mailbox-read
  connector and `m365-live-context` tool, and a
  bounded RMM device/alert/script lookup and script preview over the shared
  provider contract; the local adapter blocks execution, while reviewed
  NinjaOne, Datto, and N-central adapters expose bounded
  write paths, N-able N-sight exposes tenant-scoped device, failing-check,
  outage, antivirus-threat, and Backup & Recovery session inventory, mapped patch reads, and approval-gated
  patch approval, TimeZest exposes tenant-mapped scheduling-request reads and an
  approval-gated documented scheduling-request create action, ScalePad
  exposes separately mapped Core client inventory, ControlMap risk summaries,
  and Lifecycle Manager goal and assessment reads,
  Kaseya
  VSA X exposes organization-scoped device and
  notification reads, and ScreenConnect exposes tenant-scoped session/device
  reads through its documented RESTful API Manager extension plus an optional
  local command catalog with approval-gated command submission. This is
  alongside tenant-scoped HaloPSA ticket and Hudu
  documentation read tools for Hudu, IT Glue (including bounded document-content
  search), Confluence, Notion, and SharePoint (including bounded Graph drive search), and
  ticket lookup tools for ConnectWise PSA, Syncro, ServiceNow, and Autotask,
  tenant-scoped ticket runs, and approval pause/resume. Agents may
  run manually, on a persisted five-field cron schedule, or from authenticated
  deterministic event deliveries with idempotency and run-once-per-entity
  protection. Active runs can be cancelled through `/agent-runs/{id}/cancel`,
  which also revokes a pending smart-action approval. Failed and cancelled
  runs can be retried with a persisted three-retry cap; conversational and
  unrestricted execution remain outside this slice. `POST /agents/plan` and
  the Agents dashboard provide a preview-only natural-language-to-tool plan.
  Selection uses the configured model provider when available, otherwise
  deterministic rules, and is bounded to the existing catalog, tenant-scoped
  to the ticket, and annotated with its selection mode, risk, access mode, and
  approval requirements; malformed or unavailable model output falls back to
  deterministic rules and the preview never executes. A reviewed preview can be
  converted into a disabled agent draft for the existing revision and approval
  workflow. Definitions may also set
  a validated local execution window using `HH:MM` bounds and an IANA timezone;
  scheduled runs outside that window are skipped and audited. Run responses include a
  redacted operational final result for the last tool, including status,
  output, evidence, and error detail, without persisting hidden reasoning.
  Definitions can select bounded ticket, client, and local-knowledge context;
  selected context is tenant-scoped, redacted, capped, and recorded with each
  run. Agents may also shorten approval deadlines for approval-required tools;
  the policy cannot bypass or extend the tool-level approval requirement. An
  operator may also select additional tools that must pause for approval;
  this stricter policy is persisted with the agent revision and cannot grant
  write access or remove a catalog approval requirement.
- Event-triggered agent APIs under `/automation/events` and
  `/automation/event-deliveries`, with deterministic filters, redacted payloads,
  tenant checks, auditable delivery history, a technician-only bounded retry
  route for failed deliveries, and a local scheduler that automatically retries
  due failures in batches of ten. Each delivery may select `max_retries` from
  0-10 and `retry_delay_seconds` from 1-3600; defaults remain three attempts and
  60 seconds with capped exponential backoff.
- Agent revision history, redacted revision diffs, run-to-version links, and
  bounded rollback under `/agents/{id}/revisions`, with immutable snapshots and
  tenant-scoped restore-as-new-version.
- Workflow run history supports tenant-scoped redacted comparisons through
  `/workflow-runs/{run_id}/compare/{other_run_id}`, `workflows compare-runs`,
  and the React workflow dashboard.
  Agent run history also exposes the exact revision snapshot and supports
  approval-safe cancel and bounded retry controls under `/agent-runs`.
- Event agents may declare same-tenant dependencies; matching chains execute in
  deterministic bounded order and unmet upstream work is recorded as a failed
  delivery.
- Successful CLI/API/gallery workflows, scheduled workflows, and scheduled
  agents emit an idempotent, tenant-scoped `workflow.completed` event. Event
  agents can filter it by `workflow_template_id` or `workflow_run_id` to
  continue a bounded chain; pending-approval runs do not emit completion.
- `GET /analytics/summary` and `wait-local-agent analytics summary` include
  tenant-scoped approval decisions, distinct tickets referenced by executions,
  current `resolved`/`closed` ticket counts, explicit local ticket status
  transitions, recorded historical resolution counts, and grouped activity by
  workflow, agent, or smart action. Historical duration is calculated only when
  an explicit local/imported transition and ticket creation timestamp exist;
  existing snapshots never receive an inferred history.
- `GET /tickets/{ticket_id}/status-history` exposes the redacted,
  tenant-scoped lifecycle records used by those historical metrics.
- The React dashboard exposes the same local analytics at `/analytics`, with
  role-scoped metric cards, workflow activity, outcome details, and server-side
  date/client filters.
- The workflow catalog includes executable ticket-quality, sentiment,
  escalation, similar-ticket, security-alert, L1-resolution, and duplicate-ticket
  review templates backed by the existing
  smart-action contract. These are read-only analyses and do not mutate PSA
  records.
- A provenance-bearing local template gallery can copy reviewed core workflows
  into tenant-scoped editable records, enable or disable them, restore prior
  versions, compare redacted revision diffs, export versioned JSON artifacts,
  import validated artifacts as disabled local copies, and run them through the
  existing approval path. Imports validate the reviewed source template and
  never carry local ids or tenant identity. The gallery never permits arbitrary
  code, tools, or write permissions.
- Bounded agent backfills under `/agent-backfills` persist progress, counts,
  failures, pause/cancel state, and failed-item reruns. The React dashboard
  exposes dry-run preview, queueing, progress, controls, and failed-item
  reruns without creating a second execution engine.
- The React dashboard exposes `/executions` history with run-kind/status
  filters, redacted step detail, generated artifact metadata, and technician
  artifact downloads using the existing observability API. Smart-action runs also retain the configured
  provider/model labels as redacted operational metadata; credentials and
  hidden reasoning are never persisted.
- `POST /agent-backfills/preview` validates a bounded batch and returns a
  redacted dry-run estimate without persisting or executing it.
- Backfills default to sequential execution and may opt into up to four
  bounded workers; result accounting remains deterministic.
- Technician operators can use `/technician/chat` or
  `wait-local-agent technician-chat` for bounded requests over the existing
  smart-action catalog. Persisted, tenant-scoped technician sessions are
  available through `/technician/chat/sessions`, and the operator dashboard
  exposes the same session flow at `/technician-chat`; the CLI supports
  `--new-session`, `--session-id`, and `--client-id` for the same bounded
  history path. Only redacted operational messages, action IDs, statuses, and
  ticket references are stored.
- Operators can generate deterministic client reports from the existing local
  evidence at `/reports`: QBR, automation-opportunity, and recurring service
  review reports are also available through their matching `/reports/*` API
  routes and `wait-local-agent reports ...` commands. Repeated actions and
  follow-up candidates are review outputs only, and declared time-saved values
  are labeled estimates.
- Signed update checks with `wait-local-agent update check`.
- Pack discovery plus `wait-local-agent packs list`, `status`, and `install`.
- Founder CLI and `/founder/*` routes in the public contract, returning stable `501` responses when the founder pack is not installed.

## Requirements

- Python 3.12+
- Docker with Compose support for the appliance path
- Node.js 22 only if you want to run the dashboard outside Docker
- Optional `uv` for contributor setup

## Download & install (desktop app)

For a guided local workspace with no Docker or terminal setup, download the
installer for Windows, macOS, or Linux from the latest GitHub Release. The app
keeps your workspace on this computer, starts the local service when it opens,
and closes it with the app.

Release signing is optional. Until the repository's signing secrets are
configured, your operating system may show a first-launch unsigned-app warning.
Confirm that the installer came from the WAIT Local Agent GitHub Release before
opening it. macOS releases include separate native installers for Intel and
Apple Silicon. See
[desktop-install.md](docs/desktop-install.md) for signing secrets, local builds,
and platform-specific notes.

## Quick Start

### Appliance path

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
cp .env.example .env
docker compose up --build
```

- Dashboard: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8788`
- The dashboard is a Vite dev server that proxies API traffic to the API container.
- Persistent SQLite state lives in the `wait-local-agent-data` Docker volume.
- `scripts/install.sh` generates `.env` from `.env.example` when it is missing.
- Demo mode still works without a `.env`; Compose falls back to the built-in demo-safe defaults in `docker-compose.yml`.
- Linux collectors are container-scoped by default. Host collection is an explicit, security-sensitive opt-in; see [host-collection.md](docs/host-collection.md).

The installer helper does the same clone/copy/start flow:

```bash
scripts/install.sh
```

or:

```bash
curl -fsSL https://raw.githubusercontent.com/W-A-I-T/wait-local-agent/main/scripts/install.sh | bash
```

### Local CLI path

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
wait-local-agent doctor
```

Deterministic demo path:

```bash
scripts/demo_appliance.sh
```

Manual CLI checks against the shipped surface:

```bash
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1002
wait-local-agent workflows templates
wait-local-agent workflows run documentation-assisted-response TCK-1002
wait-local-agent workflows run ticket-sla-risk-review TCK-1002 \
  --payload '{"thresholds_minutes":{"high":240,"critical":60}}'
wait-local-agent workflows gallery
wait-local-agent workflows gallery-add ticket-triage "local operator review"
wait-local-agent workflows gallery-export <gallery-id> > template.json
wait-local-agent workflows gallery-import template.json --client-id acme
wait-local-agent agents list
wait-local-agent approvals list
wait-local-agent events list
wait-local-agent connectors validate halopsa
wait-local-agent connectors validate hudu
wait-local-agent connectors connectwise-health
wait-local-agent connectors connectwise-tickets
wait-local-agent connectors connectwise-companies
wait-local-agent connectors syncro-health
wait-local-agent connectors syncro-tickets
wait-local-agent connectors syncro-ticket-comments <ticket-id>
wait-local-agent connectors syncro-customers
wait-local-agent update check
wait-local-agent packs status
```

Cloud inventory connectors are governed read-only adapters for AWS, Azure,
GCP, and Microsoft 365. They require a vault credential reference and never
persist credential material. See the provider-specific permission guides:

- [AWS](docs/cloud-permissions-aws.md)
- [Azure](docs/cloud-permissions-azure.md)
- [GCP](docs/cloud-permissions-gcp.md)
- [Microsoft 365](docs/cloud-permissions-m365.md)

## Authentication and Demo Mode

Demo mode keeps local walkthroughs simple:

```text
WAIT_DEMO_MODE=true
WAIT_API_TOKEN=
WAIT_ADMIN_TOKEN=
WAIT_TECH_TOKEN=
WAIT_VIEWER_TOKEN=
```

For any shared LAN, appliance, or production-style install, disable demo mode and set role tokens:

```bash
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=<legacy-admin-token>
WAIT_ADMIN_TOKEN=<admin-token>
WAIT_TECH_TOKEN=<tech-token>
WAIT_VIEWER_TOKEN=<viewer-token>
```

Behavior:

- `WAIT_API_TOKEN` is the legacy admin-equivalent token.
- `WAIT_ADMIN_TOKEN` grants admin routes.
- `WAIT_TECH_TOKEN` grants technician routes.
- `WAIT_VIEWER_TOKEN` grants read-only routes.
- `WAIT_END_USER_TOKEN` grants only the separately enabled, fixed-scope
  end-user ticket routes; pair it with `WAIT_END_USER_CLIENT_ID`,
  `WAIT_END_USER_USER_ID`, and `WAIT_END_USER_SUPPORT_ENABLED=true`.
- When that mode is enabled, open `/end-user` for the separate client support
  surface. It supports local request creation, requester-scoped status lookup,
  isolated requester/support messages, and technician escalation without
  exposing the operator dashboard. Technicians can review and add local
  support replies from the Tickets screen; this is local conversation state,
  not live PSA synchronization or outbound delivery.
- The end-user surface can use local, tenant-scoped display branding through
  `WAIT_END_USER_BRAND_NAME`, `WAIT_END_USER_BRAND_TAGLINE`, and optional local
  `WAIT_END_USER_BRAND_LOGO_DATA_URI`, `WAIT_END_USER_BRAND_ACCENT_COLOR`, and
  `WAIT_END_USER_BRAND_SURFACE_COLOR`. Logos must be local base64 PNG/JPEG/WebP/GIF
  data URIs; remote image URLs are rejected. The authenticated
  `/end-user/config` response contains only those validated display values; it never
  returns client identity, credentials, or operator settings. End-user ticket
  responses contain only the requester's redacted subject/body and status
  fields, never the client ID.
- When `WAIT_DEMO_MODE=true`, requests resolve as local admin for demo use.

## Configuration

The complete shipped env surface is documented in [.env.example](.env.example). High-signal settings:

```text
WAIT_DATA_PATH=.wait-local-agent/state.db
WAIT_ALLOWED_DOC_ROOT=examples/sample_docs
WAIT_SECRETS_BACKEND=env
WAIT_VAULT_PATH=.wait-local-agent/vault
WAIT_ALLOW_WRITE_ACTIONS=false
WAIT_ALLOW_CLOUD_FALLBACK=false
WAIT_ALLOW_LLM_INFERENCE=false
WAIT_OFFLINE_MODE=false
WAIT_REMOTE_MODEL_PROVIDER=
WAIT_REMOTE_MODEL_BASE_URL=
WAIT_REMOTE_MODEL_NAME=
WAIT_REMOTE_MODEL_API_KEY=
WAIT_REMOTE_MODEL_TIMEOUT_SECONDS=20
# Optional operator-supplied rates; no provider pricing is inferred.
WAIT_MODEL_INPUT_COST_USD_PER_MILLION_TOKENS=
WAIT_MODEL_OUTPUT_COST_USD_PER_MILLION_TOKENS=
WAIT_VECTOR_BACKEND=sqlite
WAIT_CONNECTOR_TIMEOUT_SECONDS=20
WAIT_SCHEDULER_ENABLED=true
WAIT_RATE_LIMIT_ENABLED=true
WAIT_RATE_LIMIT_GENERAL=100/minute
WAIT_RATE_LIMIT_CONNECTOR=10/minute
WAIT_UPDATE_CHANNEL_URL=
WAIT_UPDATE_PUBKEYS=
WAIT_LICENSE_KEY=
WAIT_LICENSE_SECRET=
WAIT_PACK_SIGNING_SECRET=
```

Model operation is local-only by default. Deterministic mode requires no model
service; setting `WAIT_ALLOW_LLM_INFERENCE=true` enables the configured local
OpenAI-compatible endpoint. Remote fallback requires both
`WAIT_ALLOW_CLOUD_FALLBACK=true`, `WAIT_ALLOW_LLM_INFERENCE=true`, and all
`WAIT_REMOTE_MODEL_*` values. The remote provider may be `anthropic`, `deepseek`, `kimi`, or
`openai-compatible`; for the OpenAI-compatible labels, the operator must
provide a documented compatible endpoint and model name. WAIT does not ship
provider credentials, guess endpoints, or send remote requests in local-only
mode. Set `WAIT_OFFLINE_MODE=true` to deny remote model calls even when the
remote fallback configuration is complete. Remote prompts are bounded and redact common credentials, email
addresses, phone numbers, and local paths. If both optional cost-rate settings
are supplied, execution metadata and `/analytics` report a configured cost
estimate from provider-reported input/output tokens; missing rates or usage
remain explicitly unpriced.
Administrators can explicitly run `GET /settings/providers/health` (or use
“Check model health” in Settings) to query the configured provider model list;
offline, disabled, unsupported, malformed, unavailable, and missing-model
states remain visible and no credentials are returned.
Model calls use a fixed two-retry budget for transient rate-limit, timeout,
server, and transport failures. Non-retryable failures stop immediately, and
the retry count is retained only as safe provider metadata.

## Secrets Vault and Encrypted Backups

The default secrets backend is plain environment variables. For longer-lived appliances and encrypted backups, switch to the Fernet vault:

```bash
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=.wait-local-agent/vault
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
wait-local-agent secrets set WAIT_BACKUP_FERNET_KEY '<generated-fernet-key>'
wait-local-agent backup create .wait-local-agent/backups/state.db.enc --encrypt
wait-local-agent backup restore .wait-local-agent/backups/state.db.enc --encrypted
```

Notes:

- Encrypted backups require `WAIT_SECRETS_BACKEND=fernet`.
- `WAIT_BACKUP_FERNET_KEY` must exist in the local vault before `--encrypt` or `--encrypted` works.
- `wait-local-agent secrets list` prints key names only.

## Connectors

### HaloPSA

Required settings:

```text
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
```

To manually prepare an approval-gated sync of a local end-user message to an
existing HaloPSA ticket, also configure an explicit tenant mapping:

```text
WAIT_HALOPSA_CLIENT_MAP_JSON={"acme":"12345"}
```

The `/tickets` conversation controls verify the external ticket belongs to the
mapped HaloPSA client before creating an `add_note` approval draft. This is a
manual operator action; it does not provide automatic PSA polling or direct
end-user writes.

Credential validation:

```bash
wait-local-agent connectors validate halopsa
```

Read commands:

```bash
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket HALO-1002
wait-local-agent connectors halopsa-notes HALO-1002
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-assets <client-id>
wait-local-agent connectors halopsa-categories
```

Write path:

```bash
wait-local-agent connectors draft-halopsa HALO-1002 add_note \
  --field note="Internal note ready for review"
wait-local-agent approvals show 1
wait-local-agent approvals edit-field 1 note="Reviewed by technician"
wait-local-agent approvals update 1 approved "approved by technician"
wait-local-agent connectors execute-halopsa 1
```

Live HaloPSA writes require:

- outbound connector connection checks explicitly enabled
- `WAIT_ALLOW_WRITE_ACTIONS=true`
- configured credentials
- a pending draft
- explicit approval

The shared smart-action catalog also exposes approval-gated
`halopsa-ticket-add-note`, `halopsa-ticket-draft-response`,
`halopsa-ticket-status-update`, `halopsa-ticket-assign-technician`, and
`halopsa-ticket-update-fields`. Each action remains tenant-scoped to one
ticket, validates its action-specific fields, and reports provider failures
without fake success.

ConnectWise PSA status, assignment, and allowlisted ticket-field updates are
also exposed through the shared catalog as approval-gated
`connectwise-ticket-status-update`, `connectwise-ticket-assign-technician`, and
`connectwise-ticket-update-fields` actions.

### Hudu

Required settings:

```text
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
```

Validation:

```bash
wait-local-agent connectors validate hudu
```

Read commands:

```bash
wait-local-agent connectors hudu-health
wait-local-agent connectors hudu-companies
wait-local-agent connectors hudu-articles
wait-local-agent connectors hudu-article ARTICLE-1
wait-local-agent connectors hudu-folders
```

Hudu is read-only in the public repo.

### IT Glue

Required settings:

```text
WAIT_ITGLUE_BASE_URL=https://api.itglue.com
WAIT_ITGLUE_API_KEY=
WAIT_ITGLUE_PAGE_SIZE=25
```

Read commands cover organization-scoped documents and document folders:

```bash
wait-local-agent connectors validate itglue
wait-local-agent connectors itglue-health
wait-local-agent connectors itglue-organizations
wait-local-agent connectors itglue-documents <organization-id>
wait-local-agent connectors itglue-document <document-id>
wait-local-agent connectors itglue-folders <organization-id>
```

The Agents catalog also exposes the read-only `itglue-documentation-search`
tool for bounded organization-scoped document-name and text/step-content
search. It inspects at most 50 listed candidates and never writes to IT Glue.

The API mirrors these commands under `/connectors/itglue/*`. The API key stays
in the settings/vault boundary, requests are read-only and bounded, and live
network access remains gated by `WAIT_ALLOW_HTTP_PROBING` ([IT Glue API documentation](https://api.itglue.com/developer/)).

### Confluence Cloud

Required settings:

```text
WAIT_CONFLUENCE_BASE_URL=https://your-site.atlassian.net
WAIT_CONFLUENCE_EMAIL=
WAIT_CONFLUENCE_API_TOKEN=
WAIT_CONFLUENCE_PAGE_SIZE=25
```

Read commands cover bounded page listing, optional space/title filters, cursor
continuation, and page detail:

```bash
wait-local-agent connectors validate confluence
wait-local-agent connectors confluence-health
wait-local-agent connectors confluence-pages
wait-local-agent connectors confluence-page <page-id>
```

The API mirrors these commands under `/connectors/confluence/*`. Direct API
access uses Confluence Cloud basic authentication from settings/vault, only
GET requests are issued, and live network access remains gated by
`WAIT_ALLOW_HTTP_PROBING` ([Confluence REST API v2](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/)).

### Notion

Required settings:

```text
WAIT_NOTION_BASE_URL=https://api.notion.com
WAIT_NOTION_API_TOKEN=
WAIT_NOTION_VERSION=2026-03-11
WAIT_NOTION_CLIENT_PAGE_MAP_JSON={"acme":["11111111-2222-3333-4444-555555555555"]}
WAIT_NOTION_CLIENT_DATA_SOURCE_MAP_JSON={"acme":["66666666-7777-8888-9999-000000000000"]}
WAIT_NOTION_PAGE_SIZE=25
```

Notion reads require an explicit local client-to-page UUID map. Bounded title
search uses Notion's documented `POST /v1/search` endpoint, then filters the
provider response to the mapped page IDs. Page reads retrieve metadata and
bounded markdown through `GET /v1/pages/{page_id}` and
`GET /v1/pages/{page_id}/markdown`:

```bash
wait-local-agent connectors validate notion
wait-local-agent connectors notion-health
wait-local-agent connectors notion-pages acme --query MFA
wait-local-agent connectors notion-page <page-id> acme
wait-local-agent connectors notion-data-source-pages <data-source-id> acme
wait-local-agent connectors notion-data-source <data-source-id> acme
```

The API mirrors these commands under `/connectors/notion/*`. A separate,
explicit client-to-data-source map enables bounded first-page row queries via
Notion's documented data-source query endpoint; the query body is fixed to a
bounded read and supports cursor continuation. Data-source metadata retrieval
returns only the mapped data-source ID and bounded property-name/type schema
from the documented retrieve endpoint. Page comments are the only Notion write
surface: `notion-page-comment` previews a bounded Markdown comment locally and
creates it only after the existing approval flow resumes it. The approved
provider call uses Notion's documented `POST /v1/comments` contract; live
network access requires `WAIT_ALLOW_HTTP_PROBING=true` and writes also require
`WAIT_ALLOW_WRITE_ACTIONS=true`. Requests use the configured bearer token and
`Notion-Version` header ([Notion API introduction](https://developers.notion.com/reference/intro), [search](https://developers.notion.com/reference/post-search), [page markdown](https://developers.notion.com/reference/retrieve-page-markdown), [retrieve a data source](https://developers.notion.com/reference/retrieve-a-data-source), [query a data source](https://developers.notion.com/reference/query-a-data-source), [create a comment](https://developers.notion.com/reference/create-a-comment), [capabilities](https://developers.notion.com/reference/capabilities)). Broader page updates, property writes, and other comments APIs remain unavailable. The action is exposed through the generic smart-action API/CLI/Agents catalog and the Connectors dashboard approval form.

### SharePoint

Required settings:

```text
WAIT_SHAREPOINT_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_SHAREPOINT_ACCESS_TOKEN=
WAIT_SHAREPOINT_PAGE_SIZE=25
```

Read commands cover bounded site metadata and SharePoint document-library
metadata, including folder-scoped listing:

```bash
wait-local-agent connectors validate sharepoint
wait-local-agent connectors sharepoint-health
wait-local-agent connectors sharepoint-sites
wait-local-agent connectors sharepoint-site <site-id>
wait-local-agent connectors sharepoint-documents <site-id>
wait-local-agent connectors sharepoint-document <site-id> <item-id>
```

The Agents catalog also exposes `sharepoint-documentation-search` for bounded
site or folder-hierarchy search through Microsoft Graph. The API mirrors these
commands under `/connectors/sharepoint/*`. The supplied
delegated or application bearer token stays in settings/vault; only bounded
Graph GET requests are issued, supported text content is downloaded only through
the explicit content tool, and live network access remains gated by
`WAIT_ALLOW_HTTP_PROBING` ([SharePoint in Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/resources/sharepoint?view=graph-rest-1.0)).

### Microsoft 365 identity, group, license, mailbox, and Intune context

The live Microsoft Graph surface is intentionally limited to bounded user,
group, tenant subscribed-license, mailbox-folder, and Intune managed-device
context plus explicitly approval-gated user lifecycle, direct user license,
session revocation, managed-device sync, reboot, and retirement, mailbox settings, message move,
message read-state, and message deletion operations.
Configure an
externally acquired delegated or application bearer token:

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
```

Use the connector validation, health, and lookup commands. Omitting
`--identity` returns a bounded user/group page; supplying a user ID or user
principal name performs a tenant-scoped lookup. Mail-folder reads require an
explicit identity:

```bash
wait-local-agent connectors validate m365
wait-local-agent connectors m365-health
wait-local-agent connectors m365-users
wait-local-agent connectors m365-users --identity user@example.com
wait-local-agent connectors m365-groups
wait-local-agent connectors m365-groups --identity helpdesk@example.com
wait-local-agent connectors m365-licenses
wait-local-agent connectors m365-mail-folders --identity user@example.com
wait-local-agent connectors m365-mail-messages user@example.com inbox-id
wait-local-agent connectors m365-managed-devices
wait-local-agent connectors draft-m365-managed-device-sync device-1
wait-local-agent connectors draft-m365-managed-device-reboot device-1
wait-local-agent connectors draft-m365-managed-device-retirement device-1
wait-local-agent connectors draft-m365-password-reset user@example.com WAIT_M365_TEMP_USER
wait-local-agent connectors draft-m365-authentication-method-remove user@example.com --method-type fido2 --method-id method-1
wait-local-agent connectors draft-m365-mailbox-settings user-1 --setting locale=en-US
wait-local-agent connectors draft-m365-mail-message-move user-1 inbox-id message-id archive-id
wait-local-agent connectors draft-m365-mail-message-read-state user-1 inbox-id message-id --unread
wait-local-agent connectors draft-m365-mail-message-delete user-1 inbox-id message-id
```

Graph reads use only bounded GET requests. License reads return tenant subscribed-SKU
metadata and aggregate consumption/prepaid counts; per-user license details,
and mailbox reads return selected root-folder and bounded message metadata;
message bodies, previews, attachments, and hidden folders are not expanded.
Message moves are separately admin-approved through
`POST /connectors/m365/mail-messages/move-drafts` or
`draft-m365-mail-message-move`; only the destination folder ID is sent to
Graph. Read-state changes are separately admin-approved through
`POST /connectors/m365/mail-messages/read-state-drafts` or
`draft-m365-mail-message-read-state`; only the boolean `isRead` field is sent
to Graph. Deletion is separately admin-approved through
`POST /connectors/m365/mail-messages/delete-drafts` or
`draft-m365-mail-message-delete`; it sends no request body and only deletes the
explicitly identified message. Permanent deletion, send, and message-content
operations remain unavailable. These same three bounded message mutations are
also available through the shared smart-action catalog for planner and agent
use.
User creation requires `WAIT_ALLOW_WRITE_ACTIONS=true`, an admin approval, and
an encrypted-vault reference to the temporary password. Create a draft through
`POST /connectors/m365/users/drafts`, approve it through the approval queue, and
execute it through `POST /connectors/m365/approval-requests/{id}/execute` (or
the matching `draft-m365-user` and `execute-m365-user` CLI commands). The
password itself is never accepted in the approval payload or returned by the
API. Approved disable/offboarding is exposed through
`POST /connectors/m365/users/disable-drafts`, the same approval queue, and
`draft-m365-user-disable` / `execute-m365` CLI commands. It issues only
`PATCH /users/{id | userPrincipalName}` with `accountEnabled=false`; it does
not remove group memberships or licenses or delete mailbox data. The shared
smart-action catalog also exposes the admin-only `m365-user-offboarding`
operation for an explicit user identity plus directory ID. After approval it
disables the account and then revokes active sessions; if the second step
fails, the run records a partial failure and does not report success.
Password reset is also admin-approved through
`POST /connectors/m365/users/password-reset-drafts` or
`draft-m365-password-reset`; the temporary password is resolved only from a
`WAIT_M365_TEMP_...` local-vault entry. It uses Graph's documented user
`passwordProfile` update and never stores or returns the password. MFA recovery
is deliberately narrower: `POST /connectors/m365/users/authentication-method-drafts`
or `draft-m365-authentication-method-remove` removes one explicitly identified
FIDO2, Microsoft Authenticator, phone, or software OATH method. There is no
reset-all operation; method type and ID are validated and every write remains
approval-gated.
The same catalog exposes admin-only `m365-user-onboarding`, which accepts the
same validated user fields as the dedicated creation API plus a
`WAIT_M365_TEMP_...` local-vault reference. The temporary password is read
only after approval and is never persisted in the action payload, output, or
audit record. The same catalog also exposes admin-only `m365-group-membership`, which accepts
only immutable group and user directory object IDs plus an explicit `add` or
`remove` operation; membership changes remain approval-gated and report
provider failure without fake success. The catalog also exposes admin-only
`m365-license-change`, which accepts immutable user IDs, one to fifty SKU GUIDs,
and an explicit `add` or `remove` operation; license changes remain
approval-gated and report provider failure without fake success. The catalog
also exposes admin-only `m365-session-revocation`, which accepts one immutable
user ID and revokes active sessions only after approval. Provider failures are
reported as failures without fake success. The catalog also exposes admin-only
`m365-mailbox-settings`, which accepts only the allowlisted time zone, locale,
date-format, and time-format fields for one explicit user identity. Updates
remain approval-gated and provider failures are reported without fake success.
The shared catalog also exposes admin-only `m365-mail-message-move`, which
accepts one explicit user, source folder, message, and destination folder ID.
Message moves are previewed and approval-gated, and provider failures remain
explicit failures.
The shared catalog also exposes admin-only `m365-mail-message-read-state` with
a boolean read state and `m365-mail-message-delete` for one explicit message.
Both are previewed and approval-gated, with provider failures remaining explicit.
The shared catalog also exposes admin-only `m365-managed-device-sync`,
`m365-managed-device-reboot`, `m365-managed-device-retire`, and
`m365-managed-device-remote-lock`; each accepts one explicit device ID and
reuses the same approval and provider-health boundaries.
Intune managed-device retirement is exposed through
`POST /connectors/m365/managed-devices/retire-drafts` and the
`draft-m365-managed-device-retirement` CLI command; it is approval-gated and
does not expose wipe or delete. Approved Intune managed-device sync is exposed
through `POST /connectors/m365/managed-devices/sync-drafts` and the
`draft-m365-managed-device-sync` CLI command; it is approval-gated and sends no
request body. Approved Intune managed-device reboot is exposed through
`POST /connectors/m365/managed-devices/reboot-drafts` and the
`draft-m365-managed-device-reboot` CLI command; it is approval-gated and sends
no request body. Approved mailbox-settings updates are exposed
through `POST /connectors/m365/users/mailbox-settings-drafts` or the
`draft-m365-mailbox-settings` CLI command; only timezone, locale, date-format,
and time-format fields are accepted. Approved group membership changes are
exposed through `POST /connectors/m365/groups/membership-drafts` with an
explicit `add` or `remove` operation using immutable group and user IDs. The
matching CLI command is `draft-m365-group-membership`; execution uses the
same approval endpoint and `execute-m365` command. Approved direct user license
changes are exposed through `POST /connectors/m365/users/license-drafts` or
`draft-m365-license-change`; only explicit add/remove operations using immutable
user IDs and SKU GUIDs are supported. Approved session revocation is exposed
through `POST /connectors/m365/users/session-revocation-drafts` or
`draft-m365-session-revocation`. The bounded message move, read-state, and
delete actions plus Intune managed-device sync, reboot, retirement, and
remote-lock actions are also implemented through dedicated approval APIs and
the shared smart-action catalog. Broader message content, send, wipe, and
other Graph resources remain intentionally unavailable.
Managed-device reads return
selected inventory/compliance context only; serial numbers, IMEI values,
remote-assistance URLs, and action results are not requested. Group reads
return bounded group metadata only; members and owners are not expanded.

### ConnectWise PSA

Required settings:

```text
WAIT_CONNECTWISE_BASE_URL=
WAIT_CONNECTWISE_COMPANY=
WAIT_CONNECTWISE_PUBLIC_KEY=
WAIT_CONNECTWISE_PRIVATE_KEY=
WAIT_CONNECTWISE_CLIENT_ID=
WAIT_CONNECTWISE_API_VERSION=2022.1
```

Read commands are available through the CLI and the `/connectors/connectwise/*`
API routes. Set `WAIT_ALLOW_HTTP_PROBING=true` before any network request;
credentials are read from settings/vault and are never accepted in request
payloads. Ticket updates use an explicit allowlisted field map and require
`WAIT_ALLOW_WRITE_ACTIONS=true`, a pending draft, and separate approval:

```bash
wait-local-agent connectors connectwise-write-health
wait-local-agent connectors draft-connectwise CW-1002 update_status --field status_id=42
wait-local-agent approvals update 1 approved 'approved by technician'
wait-local-agent connectors execute-connectwise 1
```

Supported actions are `update_status`, `assign_technician`, and
`update_ticket_fields`. Arbitrary ConnectWise endpoints and fields are not
accepted.

### Syncro

Required settings:

```text
WAIT_SYNCRO_BASE_URL=
WAIT_SYNCRO_API_TOKEN=
```

Read commands are available through the CLI and `/connectors/syncro/*` API
routes. Ticket comment history uses the documented paginated
`GET /tickets/{id}/comments` endpoint and is exposed at
`/connectors/syncro/tickets/{ticket-id}/comments` and
`connectors syncro-ticket-comments`. The adapter uses bearer authentication,
keeps the token out of query strings and request payloads, and exposes the governed
`syncro-ticket-add-note` smart action through `/tools` and the existing
approval workflow. This action uses Syncro's documented
`POST /tickets/{id}/comment` endpoint and requires an existing local ticket in
the caller's tenant scope, `WAIT_ALLOW_HTTP_PROBING=true`,
`WAIT_ALLOW_WRITE_ACTIONS=true`, and an approved smart-action request.

The supported comment fields are `subject`, `body`, `hidden`, and
`do_not_email`; `subject` and `body` are required. Credentials are read from
settings/vault and are never accepted in action payloads. See the
[Syncro API documentation](https://api-docs.syncromsp.com/) and
[Syncro scripting API reference](https://syncro.helpjuice.com/scripting-apis/scripts-reference)
for the provider contract. The same action is available from the existing
CLI contract:

```bash
wait-local-agent smart-actions describe syncro-ticket-add-note
wait-local-agent smart-actions invoke syncro-ticket-add-note \
  --payload '{"ticket_id":"42","fields":{"subject":"Internal review","body":"Reviewed locally"}}'
```

The first invocation creates the normal approval request; execution is only
performed after that request is approved through the existing approval path.

### ServiceNow

Required settings:

```text
WAIT_SERVICENOW_BASE_URL=
WAIT_SERVICENOW_USERNAME=
WAIT_SERVICENOW_PASSWORD=
WAIT_SERVICENOW_API_VERSION=v1
WAIT_SERVICENOW_PAGE_SIZE=25
```

Read commands cover incidents and companies through the ServiceNow Table API:

```bash
wait-local-agent connectors validate servicenow
wait-local-agent connectors servicenow-health
wait-local-agent connectors servicenow-incidents
wait-local-agent connectors servicenow-incident <sys-id>
wait-local-agent connectors servicenow-companies
wait-local-agent connectors servicenow-company <sys-id>
```

The API mirrors these commands under `/connectors/servicenow/*`. Requests use
bounded pagination, explicit fields, basic authentication from settings/vault,
and read-only GET operations ([ServiceNow Table API](https://www.servicenow.com/docs/r/xanadu/api-reference/rest-apis/c_TableAPI.html)).

### Autotask PSA

Required settings:

```text
WAIT_AUTOTASK_BASE_URL=
WAIT_AUTOTASK_USERNAME=
WAIT_AUTOTASK_SECRET=
WAIT_AUTOTASK_INTEGRATION_CODE=
WAIT_AUTOTASK_PAGE_SIZE=50
```

Read commands cover tickets and companies through Autotask's REST API:

```bash
wait-local-agent connectors validate autotask
wait-local-agent connectors autotask-health
wait-local-agent connectors autotask-tickets
wait-local-agent connectors autotask-ticket <ticket-id>
wait-local-agent connectors autotask-companies
wait-local-agent connectors autotask-company <company-id>
```

The API mirrors these commands under `/connectors/autotask/*`. Credentials are
sent only in the documented request headers, network access remains gated by
`WAIT_ALLOW_HTTP_PROBING`, and the Agents catalog exposes approval-gated
`add_note`, `add_time_entry`, `update_status`, `update_resolution`, and
`assign_technician` actions only when `WAIT_ALLOW_WRITE_ACTIONS=true`. The actions use the
documented `TicketNotes` and `Tickets` contracts; `noteType`, `publish`, the
status ID, resolution text, assigned resource ID, and time-entry resource/role,
date, hours, and summary values are explicit operator-supplied instance values
rather than invented defaults. Broader Autotask mutations
remain unavailable ([Autotask REST API](https://psa.datto.com/help/DeveloperHelp/Content/APIs/REST/REST_API_Home.htm), [TicketNotes entity](https://psa.datto.com/help/DeveloperHelp/Content/APIs/REST/Entities/TicketNotesEntity.htm), [TimeEntries entity](https://psa.datto.com/help/DeveloperHelp/Content/APIs/REST/Entities/TimeEntriesEntity.htm), [Tickets entity](https://psa.datto.com/help/DeveloperHelp/Content/APIs/REST/Entities/TicketsEntity.htm)).

### NinjaOne RMM

The bounded NinjaOne adapter is configured with an OAuth access token and an
explicit per-tenant organization map:

```text
WAIT_NINJAONE_BASE_URL=https://app.ninjarmm.com/api/v2
WAIT_NINJAONE_ACCESS_TOKEN=
WAIT_NINJAONE_ORGANIZATION_MAP_JSON={"acme":42}
WAIT_NINJAONE_PAGE_SIZE=50
```

It provides tenant-scoped device/alert inventory, script catalog and preview,
approval-gated script execution, and execution-status lookup through the
existing smart-action contract. Live calls require
`WAIT_ALLOW_HTTP_PROBING=true`; execution also requires
`WAIT_ALLOW_WRITE_ACTIONS=true` and technician approval. Credentials are kept
in settings or the encrypted vault, never in action payloads. See
[NinjaOne Public API](https://app.ninjaone.com/apidocs/) and
[NinjaOne OAuth token configuration](https://www.ninjaone.com/docs/application-programming-interface-api/oauth-token-configuration/).

### Datto RMM

The public Datto RMM adapter provides bounded device inventory, open-alert
inventory, component metadata, approval-gated quick-job execution, and bounded
job-status lookup through the shared RMM contract:

```text
WAIT_DATTORMM_BASE_URL=https://your-datto-api-host/api
WAIT_DATTORMM_ACCESS_TOKEN=
WAIT_DATTORMM_SITE_MAP_JSON={"acme":"site-uid"}
WAIT_DATTORMM_PAGE_SIZE=50
```

The site map is operator-controlled and required for every request; returned
rows with a conflicting site identifier are discarded. Datto component/device
validation occurs before any quick-job write. Execution requires a completed
technician approval and `WAIT_ALLOW_WRITE_ACTIONS=true`; live calls require
`WAIT_ALLOW_HTTP_PROBING=true`. Datto's API reports job state but does not
expose completed component output. See the
[Datto RMM API documentation](https://rmm.datto.com/help/en/Content/2SETUP/APIv2.htm).

### N-able N-central

The N-central adapter provides tenant-scoped device inventory, active issues,
scheduled-task metadata, and a bounded direct-task execution/status path through
the shared RMM contract:

```text
WAIT_NCENTRAL_BASE_URL=https://your-ncentral-host
WAIT_NCENTRAL_ACCESS_TOKEN=
WAIT_NCENTRAL_ORG_UNIT_MAP_JSON={"acme":[100,101]}
WAIT_NCENTRAL_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

`WAIT_NCENTRAL_ORG_UNIT_MAP_JSON` maps each WAIT tenant/client ID to one or
more positive N-central organization-unit IDs. Returned devices, issues, and
tasks are filtered against that map. Direct tasks are limited to existing
numeric script items and devices returned for the mapped tenant, require
`WAIT_ALLOW_WRITE_ACTIONS=true` plus the existing technician approval flow, and
persist execution scope locally before status polling. WAIT sends no script
source, provider credential, or caller-supplied customer ID. See the
[N-central devices API](https://developer.n-able.com/n-central/reference/listdevices),
[active issues API](https://developer.n-able.com/n-central/docs/active-issues-api),
and [task/job API overview](https://developer.n-able.com/n-central/docs/task-job-management-apis-overview).

### N-able N-sight

The N-sight adapter is a bounded XML Data Extraction API surface for
tenant-scoped site, server, and workstation inventory plus documented failing
checks, outages, managed-antivirus threats, and Backup & Recovery sessions. It
uses an explicit local
WAIT-client-to-N-sight-client map and
rechecks the returned client before exposing bounded device and alert records:

```text
WAIT_NSIGHT_BASE_URL=https://your-n-sight-server
WAIT_NSIGHT_API_KEY=
WAIT_NSIGHT_CLIENT_MAP_JSON={"acme":123}
WAIT_ALLOW_HTTP_PROBING=true
```

The shared `rmm-device-lookup` and `rmm-alert-lookup` actions expose the mapped
inventory and provider-reported failing checks. The `nsight-outage-lookup`
action exposes bounded open and recent outages for one mapped device. The
`nsight-backup-sessions` action exposes bounded Backup & Recovery session
history for one mapped device. The
`nsight-patch-lookup`
action exposes bounded patch inventory for one mapped server or workstation
after a local device-scope recheck. The `nsight-patch-approve` action previews
and, after technician approval and the write flag, calls the documented patch
approval service only for patches present on that mapped device. Each request is limited to
mapped sites, and the adapter caps results at 25 sites, 100 devices, and 100
records per bounded read surface. The API key remains in settings or the encrypted vault and is never
accepted in action payloads or included in errors/audit records. Script
discovery, preview, execution, and polling return an explicit unavailable
result because no documented contract is claimed for those operations. The
`nsight-patch-reprocess` action uses the same approval, write-flag, inventory
recheck, tenant scope, and bounded patch-ID controls for N-sight's documented
patch reprocessing service. See
patch reprocessing service. The `nsight-patch-policy` action exposes only the
documented `do_nothing`, `ignore`, `inherit`, and `retry` operations through an
explicit allowlist with the same controls. The read-only
`nsight-antivirus-threats` action exposes documented managed-antivirus threat
records after the same mapped-device recheck; it never starts or changes an
antivirus scan. The read-only `nsight-outage-lookup` action exposes open and
recent outage records from the documented `list_outages` service after the same
mapped-device recheck. The `nsight-backup-sessions` action uses the documented
`list_mob_sessions` service after the same recheck and never starts or changes a
backup job. See
N-able's [API getting started guide](https://developer.n-able.com/n-sight/docs/getting-started-with-the-n-sight-api),
[site listing](https://developer.n-able.com/n-sight/docs/listing-sites),
[server listing](https://developer.n-able.com/n-sight/docs/listing-servers),
[workstation listing](https://developer.n-able.com/n-sight/docs/listing-workstations),
and [failing-check listing](https://developer.n-able.com/n-sight/docs/listing-failing-checks),
and [outage listing](https://developer.n-able.com/n-sight/docs/list-outages),
and [Backup & Recovery sessions](https://developer.n-able.com/n-sight/docs/list-backup-recovery-sessions),
and [patch listing](https://developer.n-able.com/n-sight/docs/list-all-patches-for-device),
and [patch approval](https://developer.n-able.com/n-sight/docs/approve-patch),
and [patch reprocessing](https://developer.n-able.com/n-sight/docs/reprocess-patch),
[patch ignore](https://developer.n-able.com/n-sight/docs/ignore-patch),
[patch inherit](https://developer.n-able.com/n-sight/docs/inherit-patch), and
[patch retry](https://developer.n-able.com/n-sight/docs/retry-patch).

### TimeZest

The TimeZest adapter exposes bounded scheduling-request reads and one
approval-gated documented create mutation through the shared smart-action
catalog. Configure one documented Autotask or ConnectWise PSA company mapping
per WAIT client:

```text
WAIT_TIMEZEST_BASE_URL=https://api.timezest.com
WAIT_TIMEZEST_API_KEY=
WAIT_TIMEZEST_CLIENT_MAP_JSON={"acme":{"connectwise_psa_company_id":209116}}
WAIT_ALLOW_HTTP_PROBING=true
```

`timezest-scheduling-request-lookup` and
`timezest-scheduling-request-create` are reachable through the generic
smart-action API, CLI, agent planner/tool catalog, and `/agents` UI. The
create action requires a client-scoped mapped company, documented appointment
type, trigger mode, resource IDs, and end-user name/email; it creates a
persisted approval draft first and only sends the documented POST after a
second technician or administrator approves it. Set
`WAIT_ALLOW_WRITE_ACTIONS=true` in addition to the HTTP probing flag for the
live write. Reads use the documented scheduling-request list endpoint and
fixed cursor page size, apply a deterministic local associated-company check,
and return bounded appointment metadata without exposing the provider
scheduling URL or end-user email. The approved create result returns the
bounded scheduling-request ID and scheduling URL; rescheduling and
cancellation remain unavailable because the documented mutation contract is
not present. See the [TimeZest API
authentication guide](https://developer.timezest.com/authentication/),
[scheduling-request API](https://developer.timezest.com/scheduling_requests/),
[pagination guide](https://developer.timezest.com/pagination/), and
[TQL guide](https://developer.timezest.com/tql/).

### ScalePad

The ScalePad adapter exposes bounded, read-only Core client, ControlMap
risk-summary, and Lifecycle Manager goal and assessment reads through the
shared smart-action catalog. Configure separate documented provider IDs per
WAIT client:

```text
WAIT_SCALEPAD_BASE_URL=https://api.scalepad.com
WAIT_SCALEPAD_API_KEY=
WAIT_SCALEPAD_CLIENT_MAP_JSON={"acme":"scalepad-client-id"}
WAIT_SCALEPAD_RISK_TENANT_MAP_JSON={"acme":"scalepad-tenant-id"}
WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON={"acme":"scalepad-lifecycle-client-id"}
WAIT_ALLOW_HTTP_PROBING=true
```

`scalepad-client-lookup`, `scalepad-risk-summary`, `scalepad-goal-lookup`, and
`scalepad-assessment-lookup` are reachable through the generic smart-action API,
CLI, agent planner/tool catalog, and `/agents` UI;
dedicated health and read routes are also available under
`/connectors/scalepad`. WAIT builds the exact documented Core client-ID or
ControlMap tenant-ID filter locally, caps each page, rechecks the returned
provider scope, and exposes only bounded, redacted records. The Core,
ControlMap, and Lifecycle Manager mappings are intentionally separate because
ScalePad's public docs do not establish that their identifiers are
interchangeable. ScalePad writes and other product APIs remain unavailable.
See the [ScalePad getting-started guide](https://developer.scalepad.com/docs/getting-started),
[List Clients reference](https://developer.scalepad.com/reference/list-clients-1),
[List Clients Risk Summaries reference](https://developer.scalepad.com/reference/03_listclientsrisksummary-1),
[List Goals reference](https://developer.scalepad.com/reference/apipublicv1goallist),
[List Assessments reference](https://developer.scalepad.com/reference/apipublicv1assessmentslist),
and [regional endpoint guide](https://developer.scalepad.com/docs/regional-endpoints-and-compliance).

### Kaseya VSA X

The bounded Kaseya VSA X adapter uses the documented v3 Basic-auth API and an
explicit WAIT client-to-organization map:

```text
WAIT_KASEYA_RMM_BASE_URL=https://your-vsa-host/api/v3
WAIT_KASEYA_RMM_TOKEN_ID=
WAIT_KASEYA_RMM_TOKEN_SECRET=
WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON={"acme":101}
WAIT_KASEYA_RMM_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

It provides organization-scoped device and notification inventory, script
catalog and preview, approval-gated script execution, and execution-status
lookup through the shared RMM actions. Every script request validates the
mapped tenant device and documented input-variable IDs; execution requires
technician approval, `WAIT_ALLOW_WRITE_ACTIONS=true`, and live HTTP probing.
Execution scope is persisted locally before status polling. Credentials remain
in settings or the encrypted vault and never enter action payloads. See the
[VSA X REST API reference](https://api.vsax.net/).

### ConnectWise ScreenConnect

The bounded ScreenConnect adapter uses the documented RESTful API Manager
extension for tenant-scoped session/device lookup and approval-gated session
notes/messages. Configure an
explicit local client-to-session UUID map:

```text
WAIT_SCREENCONNECT_BASE_URL=https://your-screenconnect-host
WAIT_SCREENCONNECT_EXTENSION_ID=
WAIT_SCREENCONNECT_AUTH_SECRET=
WAIT_SCREENCONNECT_ORIGIN=https://your-screenconnect-host
WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON={"acme":["11111111-2222-3333-4444-555555555555"]}
WAIT_SCREENCONNECT_SCRIPT_CATALOG_JSON={"collect-info":{"name":"Collect information","command":"systeminfo"}}
WAIT_ALLOW_HTTP_PROBING=true
```

The optional local catalog exposes bounded metadata, preview, and
approval-gated `SendCommandToSession` submission. The generic smart-action
catalog also exposes `screenconnect-session-note` and
`screenconnect-session-message`, which call `AddNoteToSession` and
`SendMessageToSession` only after approval. Catalog commands do not
accept runtime arguments, and execution reports provider acceptance without
claiming polling or completion. Provider-native alert lookup and script
discovery remain explicitly unavailable. See the [ScreenConnect API security overview](https://docs.connectwise.com/ScreenConnect_Documentation/Developers/ConnectWise_ScreenConnect_API_Security_Overview)
and [RESTful API Manager](https://docs.connectwise.com/ScreenConnect_Documentation/Developers/RESTful_API_Manager).

## Scheduled Workflows and Tenancy Filters

Workflow templates are listed with:

```bash
wait-local-agent workflows templates
```

Templates that require operator inputs declare them in the template payload
schema. Pass a bounded JSON object or JSON file with `--payload`; the API uses
the same object in `WorkflowRunRequest.payload`. The SLA-risk and stale-ticket
review templates require explicit positive thresholds and never infer a vendor
contract or silently treat missing ticket timestamps as evidence.
The catalog also includes approval-gated Microsoft 365 onboarding, offboarding,
password-reset, authentication-method removal, and license-request reviews;
these use the existing admin-only smart actions,
tenant scope, and local-vault/provider readiness checks.

Scheduled template jobs use the same bounded object under `params.input`, for
example `{"ticket_id":"TCK-1002","input":{"stale_after_minutes":240}}`.
Invalid or missing required inputs are recorded as failed scheduled triggers;
they do not produce a successful run.

Gallery templates can be moved between local appliances as reviewed JSON
artifacts:

```bash
wait-local-agent workflows gallery-export <gallery-id> > template.json
wait-local-agent workflows gallery-import template.json --client-id acme
```

The API equivalents are `GET /workflow-templates/gallery/{id}/export` and
`POST /workflow-templates/gallery/import`. Imports validate the source against
the built-in reviewed catalog and arrive disabled until an operator reviews and
enables them.

Workflow runs and scheduled jobs are available over API routes, including:

- `GET /scheduled-jobs`
- `POST /scheduled-jobs`
- `POST /scheduled-jobs/{job_id}/pause`
- `POST /scheduled-jobs/{job_id}/resume`
- `POST /scheduled-jobs/{job_id}/reschedule`
- `DELETE /scheduled-jobs/{job_id}`

Use `template_id` for a workflow schedule. Use `agent_id` plus `entity_id` for
an agent schedule; the agent definition must use the `scheduled` trigger and
the job's `params.input` object is passed to the bounded executor. An agent's
optional execution window is evaluated in its configured IANA timezone before
the run is created. Schedule requests accept an IANA `timezone` (default
`UTC`); cron and interval triggers use it for local-time interpretation, while
one-time `run_at` timestamps remain absolute instants.

Client reports can use the same scheduler with a deterministic, tenant-scoped
report target. Set `report_type` to `qbr`, `automation_opportunity`, or
`recurring_service_review` and pass
`params.client_id` plus either a dynamic `period_days` value from 1 through 366
or explicit ISO `period_start` and `period_end` dates:

```bash
wait-local-agent reports schedule qbr --cron "0 9 * * *" --client-id acme --period-days 90
```

The equivalent API request is `POST /scheduled-jobs` with
`{"report_type":"recurring_service_review","cron":"0 9 * * *","params":{"client_id":"acme","period_days":90,"follow_up_after_days":14}}`.
Scheduled reports reuse the local report builders and audit the created report
or the bounded failure; they do not call a remote model or provider.

Stored API views accept `client_id` filters where applicable so operators can scope tickets, approvals, audit events, workflow runs, knowledge documents, and scheduled jobs per tenant.

Communication previews are available through the `communication-draft` smart
action. `communication-send` creates an approval request and delivers only
after approval. Supported channels are `ticket_note`, `email`, `teams`,
`slack`, and `sms`; external channels use the configured SMTP/webhook adapters
and remain blocked unless both write and outbound-call flags are enabled. A
successful delivery returns an opaque local `receipt_id`, UTC `accepted_at`,
and adapter status; webhook deliveries also report the HTTP status code. The
receipt is stored in the redacted smart-action run output and is available from
`GET /smart-actions/runs` or `wait-local-agent smart-actions runs`. Provider
response bodies and credentials are never returned or persisted.

## Updates

Signed update checks are disabled by default until both settings are populated:

```text
WAIT_UPDATE_CHANNEL_URL=
WAIT_UPDATE_PUBKEYS=
```

Check for updates:

```bash
wait-local-agent update check
```

## Packs and Founder Surface

Pack operations:

```bash
wait-local-agent packs list
wait-local-agent packs status
wait-local-agent packs install /path/to/wait-pack-name.tar.gz --license <key>
```

Pack notes:

- `WAIT_PACK_SIGNING_SECRET` is required to install a signed tarball.
- `WAIT_LICENSE_KEY` unlocks licensed packs.
- When the Fernet vault is enabled, `packs install --license` stores the key in the vault; otherwise the CLI prints a reminder to set `WAIT_LICENSE_KEY` manually.
- `WAIT_LICENSE_SECRET` is loaded into config for pack-specific license flows but is not consumed by the public core directly.

Founder surface:

```bash
wait-local-agent founder scan /path/to/project
wait-local-agent founder preflight
wait-local-agent founder handoff --output handoff.md
wait-local-agent founder export-bundle --artifact-id art-1 --output bundle.json
wait-local-agent founder upload --artifact-id art-1 --yes
```

Public founder routes:

- `POST /founder/scan`
- `GET /founder/vault`
- `GET /founder/preflight/latest`
- `GET /founder/upload-preview/{artifact_id}`
- `POST /founder/upload/{artifact_id}`
- `GET /founder/lp-status`

If the founder pack is absent, founder CLI commands exit with an install hint and founder API routes return `501` with `{"error":"founder pack not installed"}`.

## More Documentation

- [docs/appliance-install.md](docs/appliance-install.md)
- [docs/connector-setup.md](docs/connector-setup.md)
- [docs/local-demo.md](docs/local-demo.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/security-model.md](docs/security-model.md)
- [docs/pack-loader.md](docs/pack-loader.md)
- [docs/update-channel.md](docs/update-channel.md)
- [docs/open-core-boundary.md](docs/open-core-boundary.md)
