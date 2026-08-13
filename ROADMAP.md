# Capability Roadmap

## Positioning

WAIT Local Agent is a local-first, open-source MSP copilot for operators who
want to keep client data on their own hardware. The default operating model is
local-first. The open core is Apache 2.0; optional paid packs can add
product-specific connectors, reports, and deployment capabilities without
changing that local default.

This is a parity roadmap, not a claim that WAIT Local Agent already provides
everything in a competing product. “Today” means behavior available in this
public repository and its documented open-core contracts. An optional pack or
a future interface is not counted as shipped here.

## Capability roadmap

| Capability | Today | Planned |
| --- | --- | --- |
| Agents vs deterministic workflows | A bounded agent definition can run a short, persisted sequence of existing smart actions for a ticket manually, from a persisted schedule, or from an authenticated deterministic event delivery. It has an explicit tool allowlist, an 8-step maximum, a 120-second execution bound, tenant scope, selectable ticket/client/local-knowledge context, approval pause/resume, active-run cancellation, bounded retries, event filters, idempotency, run-once-per-entity protection, and same-tenant event dependencies. Conversational and unrestricted autonomous agents are not shipped. | Add richer context policies and conversational surfaces. |
| Smart actions: triage, summary, suggest-resolution, find-similar-tickets, dispatch | Deterministic ticket summary/classification, cited local knowledge retrieval, explicit read-only knowledge search, ticket-quality, sentiment, escalation, similarity, dispatch suggestion, and read-only collector previews are shipped. The `/tools` catalog projects their schemas, risk, role, approval, and read/write metadata; the agent executor reuses the existing smart-action and collector services. | Extend the catalog only when a real existing capability is wrapped; keep deterministic logic ahead of model inference. |
| Triggered + scheduled runs | Persisted workflow/agent schedules use APScheduler cron, interval, and one-time triggers with validated IANA timezones; authenticated event-triggered agents use deterministic filters, idempotency, run-once-per-entity protection, bounded retry policy, execution windows, and delivery audit history. | Add broader event sources and richer trigger policy composition. |
| Backfills | Persisted agent backfills provide preflight ticket checks, bounded sequential or parallel execution, dry-run estimates, progress counts, pause/cancel state, and failed-item reruns under `/agent-backfills`. | Add connector-aware batch plans and richer operator progress views. |
| Deterministic + AI filters | Deterministic workflow gates are shipped; an optional local OpenAI-compatible provider can assist with classification, summarization, and drafting. There is no general visual combined-filter builder. | Add inspectable filter composition and local-model guardrails. |
| Technician-in-the-loop approvals | Approval requests, previews, edits, approver identity capture, bounded expiry, approval-gated HaloPSA and ConnectWise PSA writes, RMM jobs, communication delivery, and Microsoft 365 actions are shipped through the shared catalog/runtime. | Extend the same explicit approval contract to new actions and connectors. |
| Per-tool permissions | Role-based access plus connector-specific read/write and connection-check gates are shipped; this is not yet a per-tool None/read/write matrix. | Add capability-level permissions without weakening the local safety defaults. |
| Execution step logs + audit | Workflow status, connector execution history, immutable audit events, JSON/CSV export, grouped agent tool-step traces, redacted retry lineage, cancellation, artifacts, and provider/model usage metadata are shipped. | Add richer trigger context and per-step retry comparison. |
| Version history/rollback | Agent definitions and gallery templates persist immutable redacted revisions, expose diffs, link runs to the exact definition/template version, and restore prior revisions as new versions through authenticated API, CLI, and React routes. | Add richer step-level run comparison. |
| Analytics: time saved, success rate, execution volume | React `/analytics` and `/analytics/summary` provide tenant/client/date-filtered execution volume, outcomes, approval rate, ticket resolution evidence, declared time-saved estimates, and operator-priced model usage/cost estimates; credentials and hidden reasoning are excluded. | Add provider-backed lifecycle analytics and measured savings only when explicit evidence exists. |
| Templates gallery | A fixed public workflow-template catalog and tenant-scoped provenance-bearing gallery are shipped; gallery runs resolve to reviewed core implementations. | Add import/export, review lifecycle, and optional signed pack distribution. |
| PSA connectors | HaloPSA reads and approval-gated writes; ConnectWise PSA reads plus bounded status/assignment/field writes; Syncro, ServiceNow, and Autotask read routes are shipped. Broader provider write parity remains intentionally bounded. | Add one provider write surface at a time behind documented contracts and mocks. |
| RMM connectors | Local collectors plus tenant-scoped NinjaOne, Datto RMM, and read-only N-central device/alert/task metadata are shipped; NinjaOne and Datto have bounded approval-gated actions. | Add ConnectWise RMM, ScreenConnect, Kaseya, and richer N-central remediation only with provider contracts and tests. |
| Documentation connectors | Local knowledge, Hudu, IT Glue detail, Confluence page/body search, and SharePoint metadata/text-document retrieval are shipped as bounded read paths. | Add list-wide content search and binary/office extraction only with safe provider fixtures. |
| M365/Entra actions | Tenant-scoped Graph reads and approval-gated bounded user, group, license, session, mailbox, message, and Intune managed-device actions are shipped through API/CLI/tool catalog paths. | Add broader resource reads and mutations with strict IDs, approval, and provider tests. |
| Technician chat + white-label end-user support | Local technician chat and optional separately tokenized end-user ticket/status/message/escalation support are shipped. Native Teams/Slack conversation adapters, live PSA sync, outbound receipts, and branding are not shipped. | Add external channel adapters and branding only as explicit opt-ins reusing the same runtime. |
| Phone agent | Not shipped. | Deferred because it requires a telephony SaaS dependency and conflicts with the local-first default unless an operator explicitly enables a cloud-connected mode. |
| Credit metering | Hosted credit depletion is intentionally not part of the local runtime. Provider-reported tokens and optional operator-supplied input/output rates are recorded as redacted metadata and aggregated as clearly labeled estimates. | Add richer provider-native usage/cost APIs only when explicitly enabled; do not introduce hosted-credit assumptions into the open core. |
| Local collectors + cloud inventory | Read-only local collector modules are exposed through a registry, preview, confirmation, persisted runs, and evidence export. AWS, Azure, GCP, and M365 adapter classes exist as code-level groundwork in the repository, but are not exposed through any CLI command or API route. | Finish full collector-registry exposure, credential preflight, and cloud-inventory adapter UX. |
| Launch Passport evidence export | Collector bundle, hardening, and restore-evidence report types are in the public core. Founder routes define an optional-pack contract for preflight, bundle export, upload preview, explicit upload, and status; the private implementation is not present by default. | Complete the Launch Passport upload/polling integration while retaining diff preview and explicit confirmation. |

## This cycle

The following items remain open or are being prepared for the next compatible
open-core increment. Current facts are also tracked in
[`docs/status.md`](docs/status.md) and the
[`docs/neoagent-parity-matrix.md`](docs/neoagent-parity-matrix.md):

- Broader PSA, RMM, documentation, and Microsoft 365 coverage behind governed
  shared contracts and mocked provider tests.
- Bounded MSP playbook composition now includes tenant-scoped published
  aggregate definitions with validated edit, enable/disable, revision compare,
  restore-as-new-version, preview, approval-aware execution, and audit evidence;
  see [`docs/msp-playbooks.md`](docs/msp-playbooks.md). The aggregate catalog
  now also covers inactive-ticket follow-up and bounded M365 password, explicit
  authentication-method, and license reviews. Richer mappings,
  historical/provider ingestion, compliance/software review, and
  scheduled/event-triggered operations remain open.
- General conditional approval policy composition without weakening built-in
  tool requirements or tenant boundaries.
- Connector-aware backfill plans and richer provider-backed lifecycle/QBR
  evidence; estimates must remain labeled and evidence-derived.
- Native notification/channel adapters, delivery receipts, and optional
  white-label end-user branding.
- Richer model-provider lifecycle and cost APIs while preserving deterministic
  local operation and explicit offline denial.
- Browser validation in an environment with an installed Chromium binary; the
  current CI and UI test evidence remains separate from that environment gap.

## Deferred with rationale

- **Phone agent:** telephony introduces a hosted dependency, audio/data-flow
  concerns, and a default cloud path that does not fit local-first operation.
- **Teams bots:** technician chat and a white-label end-user bot require Azure
  bot registration and tenant-specific cloud connectivity. They remain an
  optional mode rather than a default appliance dependency.
- **Additional PSA and RMM vendors:** each vendor requires separate API,
  credential, permission, rate-limit, and test coverage. Prioritization will
  follow demonstrated operator demand, with read-only coverage before writes.
- **Credit metering:** hosted credits are a SaaS billing concept. The local
  equivalent is transparent usage accounting paired with analytics, without
  making local operation depend on an external balance.
- **Full natural-language builder:** a reliable builder should follow the
  reviewed template and guided-form foundation. Shipping it first would make
  workflow behavior harder to inspect and approve.

## How to influence priorities

Open a focused request in the [GitHub issue tracker](https://github.com/W-A-I-T/wait-local-agent/issues)
with the workflow, connector, evidence, or local-first constraint you need.
Include the current manual steps, the systems involved, whether read-only
access is sufficient, and what approval or audit evidence an operator must see.
Well-scoped demand helps determine which connector and template work belongs in
the open core, an optional pack, or a later cloud-connected mode.
