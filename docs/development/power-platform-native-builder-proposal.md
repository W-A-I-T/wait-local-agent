# Proposal: Power Platform Native Builder

Status: PROPOSAL — each slice needs an explicit go/no-go from the product owner.
Author: planning workstream. Implementation, if approved, follows the standard
internal packet workflow.

## Why

WAIT can today design a Power Apps artifact, design a Power Automate flow,
render both into official Power Platform YAML source
(`src/wait_local_agent/power_platform_package.py`), and run an approval-gated,
digest-bound `pac solution import` through a BUILD → DEV → TEST → PROD pipeline
with promotion evidence and a rollback path
(`src/wait_local_agent/power_platform_deployment.py`).

What it cannot do is connect to a customer's tenant. There is no environment
discovery, no connection binding, and — most importantly — **no provider-side
verification**. A stage reports `succeeded` on the strength of `returncode == 0`
from the local `pac` process plus a SHA-256 of a zip file WAIT wrote itself. The
docs are already honest about this
(`docs/consultant/consultant-power-platform-deployment.md`: a successful return
code "does not by itself prove provider-side import success"), but honest
documentation of a gap is not the same as closing it.

The product framing this unlocks is the difference between *"WAIT produces
deployable Power Platform artifacts"* and *"describe the business process,
approve the design, and it is built in your Power Platform environment."*

Three findings shaped the slicing below, and one of them is a prerequisite that
could invalidate the rest.

### Finding 1 — "pack succeeded" is not evidence, and pack has never been run

Microsoft's [solution YAML source control format
reference](https://learn.microsoft.com/en-us/power-platform/alm/solution-source-control-yaml-format)
is explicit on two failure modes that apply directly here:

> If a component is declared in `rootcomponents.yml` but its source files are
> absent … SolutionPackager emits a warning and omits that component from the
> packed `.zip`. **The pack operation still completes successfully with exit
> code 0.**

> If `solutioncomponents.yml` omits required dependency paths — such as parent
> entity folders or relationship definitions under `entityrelationships/` — the
> solution packs without error but **fails on import**.

WAIT emits `entities/` but never `entityrelationships/`. Every deployment test
injects a fake runner (`tests/test_power_platform_deployment.py`), so `pac` has
never actually executed against this package. And the `modernflows/` file shape
WAIT writes — `ModernFlow: {Trigger, Steps, ApprovalRequired}` — is WAIT's own
invention; Microsoft documents the folder as YAML-only but does not publish the
file schema in that reference, so nothing confirms Power Automate accepts it.

The package nonetheless advertises `"deployable": true` and
`"package_status": "deployable_source"`. **That claim is currently unproven.**
P0 below exists to prove or retire it, and every other slice is conditional on
it.

### Finding 2 — the canvas app path is not what it looks like

`pac canvas pack`/`unpack` are deprecated in favour of Power Platform Git
Integration and [`.pa.yaml`
source](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/power-apps-yaml).
But the *packaging* format still expects a `.msapp` binary under
`canvasapps/<name>/`. So `.pa.yaml` is the authoring format and `.msapp` remains
the packaging artifact — and WAIT can credibly synthesize neither. Recommendation
is to stop trying and make the gap an explicit, useful handoff instead.

### Finding 3 — the existing Entra sign-in cannot be reused for tenant access

`src/wait_local_agent/oidc.py` requests only `openid profile email` and discards
the token after extracting id_token claims. It is login and identity linking, not
token acquisition. The reusable template is `src/wait_local_agent/m365_auth.py`
(`M365TokenProvider`, client-credentials via `ClientSecretCredential`), and
`azure-identity` is already a pinned dependency — no new packages are required.

## The slices

### P0 — Prove the package packs and imports (prerequisite)

Materialize a package, run `pac solution pack`, then `pac solution import` into a
real development environment, and record the actual output in the task packet.
Pin the CLI floor while doing it: YAML-format support requires
`Microsoft.PowerApps.CLI` 2.4.1 or later, and WAIT never checks the `pac`
version. Expect to find at least three things: `pac solution init` in
`build_solution_command_plan` scaffolds a fresh project folder over the
materialized source, `entityrelationships/` is missing, and the `modernflows/`
schema is wrong.

- **Effort**: small to run, potentially medium to remediate.
- **Risk if skipped**: every downstream slice inherits an unproven assumption.
- **Honesty constraint**: if the package does not import, `"deployable": true`
  and `"package_status": "deployable_source"` must be corrected in the same
  packet. A field that overstates what was proven is worse than a missing
  feature.
- **Recommendation: GO, first, before anything else.** This is the cheapest,
  highest-information action available and it is mostly not code.

#### P0 result — structural half complete, and it failed

The structural half was run without a tenant, by generating a package from the
employee-onboarding demo and checking it against the published requirements.

What holds up: the manifests sit under `solutions/<name>/`, so format detection
will not fall back to XML; every path declared in `solutioncomponents.yml`
resolves to an emitted directory, so the silent-omission trap is not triggered;
and `publisher.yml` closely matches the documented minimal structure. The
Dataverse entity layer looks sound.

What does not: **the emitted flow source is not a cloud flow definition.** A
solution-aware flow is a `workflow` row requiring `category: 5`, `type: 1`,
`primaryentity: "none"`, and a `clientdata` string containing a [Logic Apps
definition](https://learn.microsoft.com/en-us/power-automate/manage-flows-with-code)
— `$schema: …/workflowdefinition.json#`, `connectionReferences`, a **named map**
of `triggers` with `type: "Request"`, and a **named map** of `actions` carrying
`runAfter` dependencies and `type: "OpenApiConnection"` inputs (`host.apiId`,
`host.connectionName`, `host.operationId`).

What is emitted is `ModernFlow: {Trigger, Steps, ApprovalRequired}` — an ordered
*list* of steps keyed by internal `ToolId` values, with a `Type:
manual_review_trigger` that is not a Power Automate trigger type. Nothing beyond
the display name corresponds. Note that the earlier fix which stopped the
trigger and steps being silently dropped was a real defect fix, but it made the
file faithfully carry WAIT's *design* data — it did not make it importable.

`"deployable": true` was also a hardcoded literal, not a computed value, on a
package that drops both the canvas app and the Copilot Studio plan into
`unsupported/`. That claim is being corrected to a per-component computation in
its own packet, so a package reports which component classes will actually
import and which are design-only.

**Still outstanding**: the live `pac solution pack` and `pac solution import`
against the development tenant. That remains required — a structural review
predicts pack behaviour, it does not prove import success. It should be run once
S0 below has produced a flow definition worth importing.

### S0 — Emit real cloud flow definitions

Promoted to first slice by the P0 result. Replace the design-document flow
source with a genuine `clientdata` payload: a Logic Apps definition carrying
`$schema`, `contentVersion`, the `$connections` and `$authentication`
parameters, a named `triggers` map, and a named `actions` map whose entries use
`runAfter` for ordering and `OpenApiConnection` inputs for connector calls.

The hard part is not the envelope, it is the mapping. Every action needs a real
`host.apiId`, `host.connectionName` and `host.operationId` — for example
`/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps` with
`operationId: ListRecords`. WAIT has no such catalogue today; its workflow steps
carry internal `tool_id` values like `m365_user_create` that correspond to
nothing on the Power Platform side. A bounded, explicit mapping table from
supported WAIT tool identifiers to connector operations is the substance of this
slice, and it should refuse to emit rather than guess at an unmapped operation.

- **Effort**: large, and the largest single piece of the epic.
- **Unblocks**: everything downstream that claims a working automation. Without
  it the pipeline can deploy Dataverse tables but never a flow that runs, which
  is most of the product's value.
- **Subsumes S4a.** `connectionReferences` live inside the same `clientdata`
  payload, so connection references stop being a separate emission problem.
- **Honesty constraint**: a flow that imports is still not a flow that runs.
  Until an operation is in the mapping table and its connector is bound, the
  package must continue to report that step as design-only rather than emit a
  plausible-looking action that fails at runtime. Partial coverage is fine;
  silent guessing is not.
- **Risk / why NO**: this is real, ongoing surface area — connector operation
  identifiers are Microsoft's to change. Scope the first cut to a deliberately
  small set of operations (Dataverse row create/list, Entra user create, licence
  assign, Teams message) rather than attempting general coverage.
- **Recommendation: GO, first.** The alternative is verifying, connecting and
  binding a pipeline whose central artifact cannot run.

### S1 — `pac` read-back verification of imports

After a zero-return import, run `pac solution list --environment <url>` through
the existing fixed-argv executor and confirm the solution appears. Substitute the
stage's top-level status with `verified` / `unverified` / `submitted` instead of a
blanket `succeeded`.

This needs no new credentials, no HTTP client, and **no schema change**:
`HaloWriteStatus` (`src/wait_local_agent/models.py`) already declares all three
literals and is the type of `ApprovalRequest.execution_status`. The pattern is a
direct copy of the HaloPSA read-back in `src/wait_local_agent/connectors.py`.

- **Effort**: small.
- **Honesty constraint**: `verified` may only mean "the CLI listed this solution
  in that environment after import". `unverified` is a recorded success with
  weaker evidence, not a failure — matching HaloPSA. The artifact digest stays
  labelled a local fact and is never merged into provider evidence.
- **Risk**: `pac` output formatting is unpinned across versions, so the presence
  check must resolve to `unverified` on any parse ambiguity, never `verified`.
- **Recommendation: GO, immediately after P0.** Highest value per unit of risk in
  the whole epic. Explicitly interim — S5 supersedes its evidence quality.

### S2 — "Connect Microsoft" as a Power Platform connector instance

Add `power_platform` as a connector type in
`src/wait_local_agent/connector_factory.py`: one Entra service principal per
tenant, vault-backed `credential_ref`, host allowlist, and the existing
`PinnedIpTransport`. Extend `M365TokenProvider` with a scope parameter and **key
its token cache by scope** — today `_cached_token` is a single slot, so a
scope-agnostic cache would hand a Graph token to a Dataverse call and surface it
as a confusing 401.

Two traps worth stating in the packet. Do **not** add the type to `_BUILDERS`;
that set drives `IngestionPoller`, and a deployment connector is not a ticket
ingestion source. And a token acquired is **not** a permission proven — the
instance may only become `active` after a real read succeeds.

- **Effort**: medium. The hinge: S3, S4b and S5 are all blocked on it.
- **Risk**: this is the epic's SSRF surface. The admin API origin can be a
  code-level constant, but Dataverse organisation URLs are *discovered*, and
  therefore influenced by a provider response. They must pass
  `validate_provider_origin` with an explicit host policy before any request.
- **Boundary change**: ROADMAP.md currently treats direct Microsoft management
  APIs as an explicit boundary. Both APIs used here are publicly documented, so
  this is defensible — but it must be an explicit ROADMAP edit in the same PR,
  not quiet drift.
- **Recommendation: GO, but only after P0 and S1 have shown the pipeline works.**

### S3 — Environment discovery and DEV/TEST/PROD role binding

`GET https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments?api-version=2020-10-01`,
which supports service-principal authentication. Operators pick environments from
a discovered list instead of hand-typing `environment_url` into
`deployment_targets`, where today any well-formed string is accepted.

Store them in a new `power_platform_environments` table modeled on the existing
`client_connector_mappings` pattern — one tenant, many environments, each with a
role and the principal who asserted it.

- **Effort**: medium.
- **Honesty constraint**: an empty result means "no environments visible to this
  service principal", never "this tenant has none" — callers must be Power
  Platform administrators, so an empty list is usually a permissions fact. And
  dev/test/prod is an **operator assertion, not a discovered property**; store and
  render who claimed it.
- **Risk**: requires the customer to grant a tenant-wide administrative
  principal. Some clients will refuse, so manual `environment_url` entry must
  remain supported. Do not make discovery mandatory.
- **Recommendation: GO if S2 lands.**

### S4a — Connection references and environment variables in the package

Today `_emit_flow_artifact` and `_emit_connector_artifact` emit **zero**
connection references, so `pac solution create-settings` against the current
package would produce a near-empty file. Per the Microsoft reference,
`environmentvariabledefinitions/` holds XML files and values live in
`environment_variable_values.json`.

- **Effort**: medium, and it needs **no credentials at all** — it can run in
  parallel with S2 under a different owner.
- **Honesty constraint**: a connection reference is a name, not a connection.
  `credentials_included: false` stays true and gains a sibling such as
  `bindings_resolved: false`.
- **Superseded by S0 for flows.** Flow `connectionReferences` live inside the
  `clientdata` payload S0 produces, so S0 absorbs that half. What remains here is
  the standalone `environmentvariabledefinitions/` and
  `environment_variable_values.json` emission, which is still needed for S4b and
  is still credential-free. Scope S4a to environment variables only once S0 is
  underway.
- **Recommendation: GO, reduced to environment variables, after S0.**

### S4b — Settings-file binding at import

`pac solution create-settings --solution-zip <zip> --settings-file <file>`, then
`pac solution import --settings-file <file>`. Documented and not deprecated. This
is what makes multi-environment promotion genuinely repeatable rather than
leaving a maker to rebind connections by hand after every import.

- **Effort**: medium.
- **Honesty constraint**: the settings file is credential-adjacent — connection
  identifiers are tenant data. It needs the same digest, path-confinement and
  redaction treatment as the solution zip, and binding remains a claim until an
  import returns zero *and* S1 or S5 confirms.
- **Risk**: promotion evidence now spans two artifacts, so both
  `validate_promotion_evidence` and `validate_promotion_source` grow. Non-trivial
  against a coverage floor that is already knife-edge.
- **Recommendation: GO after S3, not before.**

### S5 — Dataverse read-back verification

`GET {org}/api/data/v9.2/solutions?$filter=uniquename eq '...'`, plus
`solutioncomponents` and `workflows`. Real evidence — solution version, managed
flag, component count, flow state — replacing S1's presence check.

- **Effort**: medium.
- **Honesty constraint**: record **which identity observed what**. The write goes
  through the local `pac` auth profile; the read goes through the service
  principal. Those are different identities and conflating them would be exactly
  the kind of overclaim this codebase avoids. A `workflow` row existing is also
  not a flow that runs — do not infer health from presence.
- **Risk**: needs a Dataverse application user with a security role in each
  environment, a second provisioning step beyond S2's Entra app. If customers
  balk, S1 is an acceptable ceiling.
- **Recommendation: GO last, if S2 and S3 landed cleanly.**

### S6 — Git-Integration-compatible workspace layout

Emit into the `SourceCode` layout that Power Platform Git Integration expects, so
WAIT's Dataverse, flow and connector source can share a repository with
maker-authored canvas apps. Turn the `unsupported/components.json` entry from a
dead end into an actionable handoff that names the path where the canvas app
belongs.

- **Effort**: small, fully independent, no credentials.
- **Honesty constraint**: "layout compatible with Git Integration" is not "WAIT
  builds canvas apps". The unsupported entry stays; only its reason becomes
  useful.
- **Recommendation: GO whenever there is capacity.** This is the honest version
  of the "native builder" promise for the app layer.

### S7 — Canvas app generation

Full `.pa.yaml` synthesis targets a versioned format Microsoft steers makers to
author in Studio, while packaging still wants a `.msapp` binary. The strongest
claim WAIT could ever make about output it cannot open is "these files exist" —
not "this app works" — and it would carry a permanent per-release verification
burden against a format WAIT does not control.

- **Effort**: large and ongoing.
- **Recommendation: NO this cycle.** Revisit only with (i) a named customer
  asking, (ii) a development tenant and an owner for per-release
  re-verification, and (iii) S4a landed, and then as *curated templates whose
  bindings are rewritten*, never as free-form synthesis. S6 delivers most of the
  practical value at a fraction of the cost.

## Recommended order (if approved)

Revised after the P0 result.

1. **S0** — emit real cloud flow definitions. Promoted to first: without it the
   pipeline's central artifact cannot run, and every later slice would be
   verifying, connecting and binding a flow that Power Automate rejects.
2. **P0 (live half)** — `pac solution pack` and `pac solution import` against the
   development tenant, once S0 has produced something worth importing. The
   structural half is done and its findings are recorded above.
3. **S1** — read-back verification. No new credentials; closes the largest
   remaining honesty gap.
4. **S2** — the Microsoft connection. Run **S6** in parallel here under a
   different owner; they share no files.
5. **S3** — environment discovery and role binding.
6. **S4a** (environment variables only) then **S4b** — settings-file binding.
7. **S5** — Dataverse verification, superseding S1's evidence quality.
8. **S7** — no.

Genuinely parallel: S6 with anything, and S1 with S2. Strictly sequential:
S0 → P0 live half → S1; and S2 → S3 → {S4b, S5}.

### Explicitly not recommended

- **Creating service principals from inside WAIT.** `pac admin
  create-service-principal` mints a tenant-wide administrator. An approval-gated
  product should not own its own privilege-escalation primitive. Document it as
  an operator prerequisite.
- **Routing provider reads through `pac` subprocesses.** CLI output is unstable
  across versions and none of the SSRF, DNS-rebinding or response-size defenses
  in `net_security.py` apply to a subprocess. `pac` is the write path; the
  HTTP client is the read path. S1 is a deliberate, time-boxed exception.
- **An action-type registry refactor as its own slice.** The duplication is real,
  but it has no user-visible outcome and spends budget against the coverage
  floor. Fold the touches into whichever slice needs them.

## Standing requirement

No slice ships a provider claim without a **live import into a development
tenant recorded in its packet** — a mocked runner is not verification. Every
`pac` invocation keeps the current executor contract: an approved approval
record, both write gates, a canonical argv, no shell, workspace confinement, and
bounded redacted output. Every new provider read goes through `PinnedIpTransport`
and an explicit host policy, with no exception for being a Microsoft URL. Every
new route is classified in the surface manifest. And every slice states plainly
what its evidence does *not* prove — the value of this pipeline is that its
claims are trustworthy, and a single overstated status field costs more than any
feature here adds.
