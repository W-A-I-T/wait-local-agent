# Roadmap

WAIT Local Agent is the local-first MSP automation appliance: private ticket
intelligence, cited local knowledge, HaloPSA-first workflow drafts, technician
approval, and auditable local execution.

## Phase 0: Product Packaging

- Docker Compose appliance with API, dashboard, SQLite volume, health checks, and
  repeatable environment defaults.
- Backup and restore commands for the local SQLite state store.
- One-command demo path that ingests sample runbooks and tickets, runs ticket
  intelligence, lists workflow templates, and shows event history.
- Docs that clearly separate what is ready now from the staged MSP automation
  roadmap.

## Phase 1: Sellable Local Ticket Copilot

- Harden ticket summary, classification, citation, audit, local model fallback,
  and dashboard flows.
- Persist approval comments and support approval-with-edits style review before
  any workflow or connector mutation.
- Present technician-facing views for queue, sources, approval requests,
  provider health, connector readiness, and event history.

## Phase 2: HaloPSA Connector Wedge

- Add HaloPSA read path first: tickets, clients, categories, notes, and
  asset/configuration context where available.
- Draft every write before execution, then allow approved live execution for
  internal notes, status/category updates, ticket fields, technician assignment,
  and client-safe responses.
- Require explicit technician approval for every HaloPSA mutation and log the
  request, approver decision, payload, result, and failure.

## Phase 3: Workflow Engine

- Keep the workflow engine minimal and inspectable: trigger, filter, action,
  approval policy, run state, and event log.
- Ship five MSP templates first: ticket triage, assign technician, inactive
  ticket follow-up, P1 alert, and documentation-assisted response.
- Prefer deterministic rules for routing and gating. Use local model inference
  only for classification, summarization, drafting, and reasoning support.

## Phase 4: MSP Stack Expansion

- Documentation connectors: Hudu first, then IT Glue and SharePoint.
- RMM: read-only inventory before approved script recommendation and execution.
- Microsoft 365 and Entra: read-only identity, group, license, and mailbox
  lookup before approved changes.
- Scheduled workflows for audits and recurring admin tasks.

## Phase 5: Commercial Readiness

- RBAC roles for admin, technician, and viewer.
- Tenant and client boundaries, encrypted secrets storage, connector setup
  validation, audit export, and update channel.
- WAIT MSP Pack templates plus paid deployment, hardening, and support packages.
