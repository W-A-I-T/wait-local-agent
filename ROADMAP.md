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
| Agents vs deterministic workflows | A bounded agent definition can run a short, persisted sequence of existing smart actions for a ticket manually, from a persisted five-field cron schedule, or from an authenticated deterministic event delivery. It has an explicit tool allowlist, an 8-step maximum, a 120-second execution bound, tenant scope, approval pause/resume, event filters, idempotency, run-once-per-entity protection, same-tenant event dependencies, and optional IANA-timezone execution windows for scheduled/event triggers. Conversational and unrestricted autonomous agents are not shipped. | Add richer context, retry policy, overnight windows, and conversational surfaces. |
| Smart actions: triage, summary, suggest-resolution, find-similar-tickets, dispatch | Deterministic ticket summary/classification, cited local knowledge retrieval, explicit read-only knowledge search, ticket-quality checks, similarity, and dispatch suggestion are shipped. The `/tools` catalog now projects their schemas, risk, role, approval, and read/write metadata; the agent executor reuses the existing smart-action service. | Extend the catalog only when a real existing capability is wrapped; keep deterministic logic ahead of model inference. |
| Triggered + scheduled runs | Persisted workflow/agent schedules use APScheduler cron, interval, and one-time triggers with validated IANA timezones (UTC by default), pause/resume/delete/reschedule controls; authenticated event-triggered agents use deterministic filters, idempotency, run-once-per-entity protection, and delivery audit history. | Add execution windows and broader event sources. |
| Backfills | Persisted sequential agent backfills with preflight ticket checks, progress counts, pause/cancel state, and failed-item reruns are shipped under `/agent-backfills`. | Add dry-run estimates, richer progress UI, and connector-aware batch plans. |
| Deterministic + AI filters | Deterministic workflow gates are shipped; an optional local OpenAI-compatible provider can assist with classification, summarization, and drafting. There is no general visual combined-filter builder. | Add inspectable filter composition and local-model guardrails. |
| Technician-in-the-loop approvals | Approval requests, previews, edits, approver identity capture, audited 24-hour default expiry, and approval-gated HaloPSA execution are shipped. | Add per-agent policy fields and extend the same explicit contract to new actions and connectors. |
| Per-tool permissions | Role-based access plus connector-specific read/write and connection-check gates are shipped; this is not yet a per-tool None/read/write matrix. | Add capability-level permissions without weakening the local safety defaults. |
| Execution step logs + audit | Workflow status, connector execution history, immutable audit events, JSON/CSV export, and grouped agent tool-step traces are shipped. | Add richer trigger context and failure/retry detail as new execution modes land. |
| Version history/rollback | Agent definitions now persist immutable redacted revisions, expose field-level diffs, link runs to the exact definition version, and restore a prior revision as a new version through authenticated API routes. | Add workflow-template revisions. |
| Analytics: time saved, success rate, execution volume | Local analytics expose time saved as an explicitly labeled estimate, success rate, execution volume, activity breakdowns, and approval requested/decided/rate metrics. | Add ticket-resolution and per-workflow aggregates using explainable, operator-controlled measurements. |
| Templates gallery | A fixed public workflow-template catalog and tenant-scoped provenance-bearing gallery are shipped; gallery runs resolve to reviewed core implementations. Versioned JSON metadata import/export is available without importing executable content. | Add review lifecycle and optional signed pack distribution. |
| PSA connectors | HaloPSA read paths and approval-gated writes plus read-only Autotask and ConnectWise ticket/company inventory are shipped. Syncro and ServiceNow are not shipped. | Prioritize additional PSA connectors by operator demand and safe write coverage. |
| RMM connectors | NinjaOne read-only device, alert, script metadata, and script-preview paths are shipped. Script execution and management mutations remain disabled. | Add additional read-only RMM adapters, then design explicitly approved actions. |
| Documentation connectors | Hudu and IT Glue read-only documentation context are shipped. Confluence and SharePoint are not shipped. | Add further read-only documentation adapters through reviewed connector interfaces. |
| M365/Entra actions | Bounded identity-context plus tenant-scoped user/group lookup tools read only completed M365 collector runs; no customer-facing Graph mutation surface is shipped. | Add licenses, mailbox, Intune, and further read-only identity/context operations before any approved mutation path. |
| Teams technician chat + white-label end-user bot | Not shipped. | Optional cloud-connected Teams mode after Azure bot registration, tenant isolation, and explicit data-flow controls are defined. |
| Phone agent | Not shipped. | Deferred because it requires a telephony SaaS dependency and conflicts with the local-first default unless an operator explicitly enables a cloud-connected mode. |
| Credit metering | Not applicable to the local runtime. Local usage accounting is a better fit than hosted credit depletion. | Add transparent local usage accounting alongside analytics; do not introduce hosted-credit assumptions into the open core. |
| Local collectors + cloud inventory | Read-only local collector modules are exposed through a registry, CLI/API list, credential validation, preview, confirmation, persisted runs, and evidence export. AWS, Azure, GCP, and M365 adapters are available through that governed collector surface. | Add richer connector-specific operator UX and broader identity/context actions. |
| Launch Passport evidence export | Collector bundle, hardening, and restore-evidence report types are in the public core. Founder routes define an optional-pack contract for preflight, bundle export, upload preview, explicit upload, and status; the private implementation is not present by default. | Complete the Launch Passport upload/polling integration while retaining diff preview and explicit confirmation. |

## This cycle

The following items are in progress or being prepared for the next compatible
open-core increment. “In progress” does not mean that the complete end-user
feature is already shipped:

- Full collector registry exposure, including module metadata, validation,
  preview, confirmed runs, and evidence export.
- Cloud inventory adapters with credential preflight and clear opt-in data
  flow.
- Hardening and restore evidence runs that remain inspectable and exportable.
- A host-collection Docker mode for controlled local collection.
- Smart-action framework foundations built on deterministic workflows and
  explicit local-model boundaries.
- Execution observability and analytics for run volume, outcomes, timing, and
  explainable local measurements.
- A template gallery with reviewed, provenance-bearing templates.
- Guided forms and non-developer workflow setup, followed later by broader
  natural-language composition.
- Launch Passport upload and polling integration around preview, confirmation,
  and status visibility.

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
