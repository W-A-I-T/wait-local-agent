# Proposal: Microsoft-Importable Artifact Generation (Phase 4b)

Status: PROPOSAL — each item needs an explicit go/no-go from the product owner.
Author: Claude (planning). Implementation, if approved, follows the standard
Codex packet workflow.

## Why

The Solutions Architect surface produces review-only plans for Copilot Studio,
Power Apps, and Power Automate. The endpoint taxonomy tracks the Microsoft
Copilot/Power Platform Solutions Architect role, but none of the planners emit
an artifact Microsoft tooling can import. The one exception is the Power
Platform packager, which stops one step short of producing a solution zip: it
prints the `pac solution pack` command it does not run
(`src/wait_local_agent/power_platform_package.py` — `pac_plan`).

Every item below changes a documented product boundary ("generated Power
Platform artifacts are not deployments" / review-only planners), so each is an
explicit product decision, not a bug fix.

## Items

### (a) Solution zip via `pac solution pack` — SMALLEST REAL WIN

- What: after materialize writes the YAML solution source to
  `WAIT_POWER_PLATFORM_WORKSPACE`, run the already-planned
  `pac solution pack --folder <out> --zipfile <zip>` under the exact gate
  stack the deployment executor already enforces (approval record,
  `WAIT_ALLOW_WRITE_ACTIONS`, `pac` on PATH, argv fixed, `shell=False`).
- Acceptance: the zip imports cleanly via `pac solution import` into a dev
  tenant (manual verification event) and via the existing staged-deployment
  path.
- Effort: small (one subprocess stage reusing `_run_command` patterns in
  `power_platform_deployment.py`; tests mirror existing deployment tests).
- Risk: low — local file output, no tenant contact; the import path already
  exists behind flags.
- Boundary change: "materialize is local-only" becomes "materialize can
  produce a deployable zip" — arguably already implied by the deployment
  executor consuming zips.

### (b) Power Automate `definition` JSON emitter

- What: replace the invented `manual_review_trigger` flat-step plan with a
  real Logic Apps-style workflow `definition` ($schema, contentVersion,
  triggers, actions keyed by name with runAfter), wrapped in a solution-ready
  Workflow component so item (a) can package it.
- Acceptance: the emitted flow imports into Power Automate (via solution
  import) and appears in the maker portal with correct step graph; a
  golden-file test pins the schema.
- Effort: medium — the step model must gain connector references, inputs, and
  a runAfter graph; trigger vocabulary must map to real trigger types
  (manual/HTTP/recurrence at minimum).
- Risk: medium — schema drift across Power Platform versions; mitigate with
  golden files + a documented manual import verification per release.
- Boundary change: the Power Automate planner stops being review-only.

### (c) Copilot Studio topic export

- What: emit topics (name, trigger phrases) in a format Copilot Studio
  accepts. Reality check: Copilot Studio's supported import paths are
  solution import (topics as Dataverse components) or the maker UI; there is
  no simple standalone topic-file import. Realistic v1: include a bot +
  topics skeleton in the solution package from (a), OR emit a documented
  YAML/JSON that a human pastes per topic.
- Acceptance: v1 = topics visible in Copilot Studio after solution import
  into a dev environment (manual verification event).
- Effort: medium-high (Dataverse bot component schemas are fiddly and
  under-documented; expect iteration against a live tenant).
- Risk: high relative to value until conversational flow exists — importing
  trigger-phrase-only topics gives skeletal bots. Recommend deferring behind
  (e)'s decision or pairing with a minimal dialog-node model.

### (d) Knowledge grounding for the Copilot planner — HIGH VALUE, LOCAL-ONLY

- What: `knowledge_sources` on the Copilot plan is a list of raw strings.
  Wire it to the existing retrieval stack: validate each source against
  ingested knowledge (`knowledge.py`), attach retrieval evidence
  (`vector_search.py`, `retrieval.py`), and let the plan carry grounding
  citations per topic. Optionally reuse the five documentation connectors
  (SharePoint/Hudu/IT Glue/Confluence/Notion search) to verify a source
  exists before it enters the plan.
- Acceptance: a plan built with N knowledge sources shows per-source
  validation status + sample retrieval hits; unknown sources flagged, not
  silently accepted.
- Effort: small-medium — all substrate exists; this is wiring + schema
  extension of the plan artifact.
- Risk: low — read-only, local-first, no boundary change (the plan remains
  review-only; it just stops being hollow). RECOMMENDED FIRST alongside (a).

### (e) `.msapp` / deeper Dataverse model

- What: real Canvas app source (Power Fx, controls, bindings) and Dataverse
  relationships/lookups/option sets/security roles.
- Reality: `.msapp` is an undocumented, versioned format; Microsoft's
  supported route is `pac canvas pack` over YAML source (Power Apps Source
  File format, still evolving). Dataverse depth is schema work in the
  solution XML.
- Effort: large; ongoing maintenance burden tracking Microsoft format churn.
- Recommendation: NO for now. Revisit after (a)+(b) prove the packaging
  pipeline with real tenants. Dataverse relationships alone (without
  `.msapp`) could be a medium-effort middle step if demanded.

### (f) Channel publication (Teams / web / embedded)

- What: publish agents to channels — Bot Framework registration, Teams app
  manifests, web-chat embeds.
- Reality: requires Azure Bot resources, app registrations, admin-consented
  Graph permissions, and manifest signing — a genuinely new operational
  surface with credential and tenant-policy implications, contradicting the
  product's "no direct Microsoft management-API client" stance unless routed
  through `pac`/Teams Toolkit CLIs the same way deployment routes through
  `pac`.
- Recommendation: NO for this cycle. If pursued later: Teams-only, via the
  Teams Toolkit CLI under the same subprocess gate pattern.

## Recommended order (if approved)

1. (d) knowledge grounding — high value, low risk, no boundary change.
2. (a) solution zip — smallest real artifact, unlocks import verification.
3. (b) Power Automate definitions — the flagship "it builds the automation".
4. (c) Copilot topics inside the solution package — after (a)+(b) stabilize.
5. (e)/(f) — deferred; revisit post-beta with live-tenant evidence.

## Standing requirements for all items

- Every subprocess invocation follows the existing `pac` executor pattern:
  approval record, flag gates, fixed argv, `shell=False`, digest evidence.
- A "manual verification event" = a human imports the artifact into a dev
  tenant and records the result in the task packet; no release claims
  "importable" without one (matches the repo's "a mock provider is not live
  verification" rule).
- Each item updates ROADMAP.md's non-goals/boundaries in the same PR.
