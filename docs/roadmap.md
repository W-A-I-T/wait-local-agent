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

## Future Open-source Leverage

WAIT Local Agent should remain the core local-first MSP appliance. When adding
major capabilities, prefer focused, replaceable open-source modules over a
large framework rewrite.

| Need | Reference project | Use |
| --- | --- | --- |
| HaloPSA connector coverage | [`amplify-msp/py-halo`](https://github.com/amplify-msp/py-halo) | MIT Python wrapper to study for HaloPSA auth, endpoint coverage, and connector behavior. |
| Hudu connector coverage | [`lwhitelock/HuduAPI`](https://github.com/lwhitelock/HuduAPI) | MIT PowerShell module to use as an endpoint/action map while keeping this project Python/httpx-native. |
| Scanned PDF and OCR ingestion | [`docling-project/docling`](https://github.com/docling-project/docling) | MIT local document parsing, OCR, tables, layout, Markdown, and JSON export. |
| Vector search backend | [`qdrant/qdrant`](https://github.com/qdrant/qdrant) | Apache-2.0 vector database for semantic MSP documentation search with metadata filters. |
| Simpler local vector backend | [`chroma-core/chroma`](https://github.com/chroma-core/chroma) | Apache-2.0 option for quick local semantic-search prototypes. |
| Human-in-loop workflow engine | [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph) | MIT option to revisit only when workflows need branching, retries, timers, pause/resume, or multi-connector state. |
| Ops/runbook automation patterns | [`StackStorm/st2`](https://github.com/StackStorm/st2) | Apache-2.0 architecture reference for future RMM, M365, trigger/action/rule/workflow, and audit patterns. |
| MSP domain model reference | [`Nine-Minds/alga-psa`](https://github.com/Nine-Minds/alga-psa) | Useful PSA domain reference, but AGPL: do not copy code into this Apache-2.0 project without a license decision. |

Open source does not automatically mean "no issue." Before copying code or
adding a dependency, check the license and distribution obligations. MIT and
Apache-2.0 are generally compatible with this repo's Apache-2.0 model. AGPL,
fair-code, source-available, and similar licenses should be treated as product
or architecture inspiration unless WAIT explicitly accepts the obligations.

Priority order remains:

1. Use Docling for document ingestion and OCR.
2. Use py-halo as HaloPSA connector guidance.
3. Use Qdrant for the planned vector backend.
4. Consider LangGraph only when workflow state becomes too complex for the
   current deterministic engine.
5. Study StackStorm for future RMM, M365, and runbook automation patterns.
