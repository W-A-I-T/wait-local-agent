# WAIT Local Agent Roadmap

## Product direction

WAIT Local Agent is the local-first execution, orchestration, connector,
approval, policy, evidence, audit, and governance runtime underneath WAIT AI
Solutions Architect. A customer problem should move through discovery,
provider-neutral solution design, governed implementation selection,
evaluation, approval, bounded delivery, monitoring, and evidence.

The open core remains useful without a remote model, cloud control plane, vendor
credential, or hosted credit balance. Deterministic policy is authoritative for
tenant and client scope, permissions, write classification, approvals,
redaction, deployment gates, and audit evidence. Model assistance may interpret
or draft from evidence, but it cannot invent evidence or override safety.

“Shipped” in this roadmap means reachable through the documented API, CLI, UI,
or local fixture and covered by relevant tests. A generated artifact is not a
deployment, a mock provider is not live verification, and an unavailable
credential or undocumented vendor API remains an explicit boundary.

## Core Platform

### Current foundation

- Local FastAPI, Typer, SQLite, scheduler, event, workflow, agent, connector,
  tool-catalog, approval, audit, evidence, backup, and redaction primitives.
- Tenant/client-scoped data access, role checks, bounded execution, cancellation,
  retries, idempotency, offline enforcement, and deterministic local behavior.
- Optional local or explicitly enabled remote provider adapters behind the same
  bounded model-provider contract.
- Inbound governed MCP and bounded outbound MCP, with host, tenant, policy, and
  execution restrictions.

### Next increments

- Capability-level permission matrices and richer, inspectable policy
  composition without weakening built-in tool requirements.
- Connector-aware plans, richer event sources, execution comparison, and
  provider lifecycle evidence.
- Stable public contracts for optional packs and provider breadth driven by
  demonstrated solution demand.

## AI Solutions Architect

### Current foundation

- Guided discovery, including tenant/principal-scoped persisted sessions with
  bounded one-question turns, explicit transcript evidence, and no-inference
  next-question state; tenant-scoped provider-neutral `SolutionBlueprint` data,
  architecture projections, workflow design, use-case catalog, delivery
  handoff, governance review, evaluation contracts, monitoring, and bounded
  supervisor/child-agent plans.
- No-probe environment discovery that matches customer declarations to the
  existing connector catalog, preserves configured/detected/
  permission-limited/not-configured/unknown states, and carries evidence into
  the blueprint candidate and architecture review.
- Deterministic architecture decisions for blueprint components, with explicit
  targets, alternatives, dependencies, permissions, licenses, read/write and
  approval boundaries, risk, data movement, complexity, reversibility, tests,
  deployment requirements, and evidence gaps.
- Reviewable Power Apps, Power Automate, connector, deployment, and delivery
  artifacts that preserve the distinction between plan, generate, validate,
  package, and deploy.

### Next increments

- Broader guided discovery ergonomics, including resumable operator views and
  richer transcript review. The canonical employee-onboarding fixture now
  demonstrates discovery-to-architecture promotion, controlled local
  evaluation, governance, delivery, and approval creation; live provider
  execution and deployment remain separate evidence-gated increments.

## Microsoft / Power Platform

### Current foundation

- Bounded Microsoft Graph and Teams reads/actions, Work IQ read boundaries,
  Power Platform connector artifacts, Power Apps metadata/build artifacts,
  Power Automate planning, and deployment-stage records.
- PAC execution is allowlisted, fixed-argument, approval-gated, bounded,
  digest-bound, shell-disabled, and reports unavailable credentials or tools
  explicitly.

### Next increments

- Complete blueprint-to-artifact validation and packaging across supported
  Copilot Studio, Power Automate, Power Apps/Dataverse, connector, and PAC
  paths.
- Promotion gates for DEV → TEST → PROD with explicit human approval,
  evaluation evidence, rollback metadata, and no inference of live success from
  local artifacts.
- Expand Work IQ only for documented operations whose path, function,
  arguments, tenant, identity, and local policy produce a deterministic
  READ/WRITE/ACTION/HIGH-RISK/BLOCKED/UNKNOWN decision. Unknown fails closed.

## MSP Operations Vertical

MSP Operations remains a first-class product vertical, not a legacy mode. The
existing ticket, PSA, RMM, Microsoft 365, documentation, reporting,
technician-chat, scheduled/event workflow, approval, and audit capabilities are
preserved and extended through the shared runtime.

### Current foundation

- Ticket triage, classification, summary, similar-ticket lookup,
  documentation-assisted resolution, ticket QA, sentiment/escalation,
  dispatch, bounded L1 actions, SLA/stale-ticket signals, and evidence-backed
  reports.
- Governed HaloPSA, ConnectWise, Syncro, ServiceNow, Autotask, RMM,
  documentation, Microsoft 365, Teams, and communication surfaces where the
  provider contract, scope, approval, audit, and tests exist.

### Next increments

- Complete reusable, versioned playbooks for triage, duplicate handling,
  resolution, dispatch, stale/SLA sweeps, onboarding/offboarding, security
  response, QBR, service review, license review, and automation-opportunity
  analysis.
- Add provider-backed connector operations one at a time, retaining explicit
  unsupported boundaries for undocumented mutations such as unsupported
  marketplace actions.
- Complete technician notifications, optional end-user support, and
  white-label flows without a second chat or execution backend.

The NeoAgent parity matrix is retained as an **MSP Operations capability
comparison** and evidence index. It is not the master product roadmap.

## Evaluation / Governance

### Current foundation

- Review-oriented evaluation contracts plus controlled local-fixture execution
  through the existing AgentService, deterministic governance and DLP mapping,
  provider/tool policy, audit evidence, redaction, and tenant/RBAC boundaries.

### Next increments

- Expand controlled evaluation from the current local AgentService fixture path
  to the full required security, provider-failure, rollback, and regression
  matrix without enabling production execution.
- Cover functional behavior, tool selection, forbidden tools, approvals,
  grounding, tenant isolation, RBAC, prompt/tool injection, secret leakage,
  unexpected writes, timeouts, retries, cancellation, provider failure,
  malformed output, duplicate prevention, partial failure, rollback, latency,
  and regression.
- Keep evaluation isolated from production unless separately authorized and
  preserve failure evidence instead of converting it to empty or successful
  results.

## Enterprise Readiness

- Maintain a repeatable backend gate: pytest at the repository threshold, Ruff,
  mypy, Bandit, pip-audit, public-surface audit, and CI.
- Maintain UI tests, production build, real-browser route/control coverage,
  responsive/accessibility checks, and loading, empty, denied, offline, and
  provider-error states.
- Verify tenant/client isolation, approval-before-write, input validation,
  redaction, injection resistance, timeout/retry/cancellation, idempotency,
  duplicate prevention, offline operation, and no fake-success paths.
- Prepare Windows/macOS signing, updater verification, provenance, rollback,
  release validation, backups, observability, and deployment hardening. Missing
  external certificates remain an explicit operational prerequisite.

## Founder / Engineering Vertical

- Preserve project inspection, evidence collection, Launch Passport handoff,
  engineering automation, local hardening, backup/restore, and release
  evidence as governed consumers of the same runtime.
- Keep founder workflows separate in audience and authorization while reusing
  the core evidence, approval, audit, and connector contracts.

## Future Integrations

Provider breadth follows actual solution demand. New PSA, RMM, documentation,
Microsoft, MCP, marketplace, and custom-service integrations require a
documented contract, bounded scope, explicit permissions, approval rules for
writes, redaction, audit evidence, failure handling, and mocked/local tests
before they are represented as shipped capability.

## Delivery and completion evidence

Every increment should identify the affected source paths, interface, tests,
security boundaries, external prerequisites, and unsupported cases. The
repository is coherent when `README.md`, this roadmap, `docs/status.md`, the
architecture documents, the parity comparison, issue backlog, and live CI all
describe the same verified behavior.
