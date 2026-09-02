# Consultant mode demo

The deterministic consultant-mode walkthrough uses synthetic input and local
artifacts only:

```bash
scripts/demo_consultant_mode.sh
```

The launcher uses an installed `wait-local-agent` command when available and
otherwise falls back to `uv run wait-local-agent`, so the walkthrough works
from a repository checkout after the project dependencies are installed. CI
runs the same script against a temporary SQLite database.

It lists the Teams use case, assesses explicit discovery evidence, builds a
reviewable Power Apps/Dataverse artifact manifest and Power Automate plan, prepares a
review-only OpenAPI custom-connector package and a separate Copilot Studio maker handoff, prints a staged `pac solution`
deployment plan, evaluates an observed tool contract, reviews governance,
reports Power Platform packaging status, composes a delivery handoff, and
summarizes local agent health. It does not call Microsoft Graph, Teams,
Dataverse, a connector host, `pac`, or a deployment command. The Power Apps
artifact is a local handoff; it is not an `.msapp` file or a deployed
Dataverse solution. The Copilot Studio output is a handoff plan; it is not a
provisioned Copilot, published channel, or live connector.

The demo inputs are under `examples/consultant/`. They contain no credentials,
provider tokens, or real customer data. The output is suitable for review and
handoff; all state-changing actions remain behind the existing approval
boundary.

## Employee-onboarding walkthrough

The canonical employee-onboarding scenario composes the existing discovery,
environment projection, blueprint, architecture, supervisor, evaluation,
governance, delivery, and audit primitives in one isolated local fixture:

```bash
scripts/demo_employee_onboarding.sh
```

The fixture seeds only `TCK-1001` for tenant `acme`. Specialist agents execute
the existing bounded `ticket-triage` action; their target Microsoft, PSA, RMM,
documentation, and Teams tools are architecture declarations, not live calls.
The walkthrough also generates and validates two deterministic review-only
manifests for Power Apps/Dataverse and Power Automate, generates a separate
Copilot Studio design handoff, and packages only the two review artifacts with a
digest. The Copilot plan is a maker handoff, not a packaged component: there is
no Power Platform packager emitter for it, and force-feeding it to the packager
remains unsupported. That package is not an
`.msapp`, solution zip, provisioned Copilot, or deployable Power Platform
package. Live provider execution and deployment remain unstarted and explicit.

Copilot Studio planning is available through the CLI/API only. There is no
Copilot Studio screen: `ui/src/screens/Consultant.tsx` contains zero occurrences
of “copilot”. A maker uses the returned topics, trigger phrases, knowledge
sources, and actions to build the Copilot by hand.

The same composition is available to an authenticated technician through
`POST /consultant/demos/employee-onboarding` when the appliance is in local
demo mode with writes disabled. The request must include the tenant-scoped
blueprint ID (or an explicitly supplied blueprint for script-style callers)
and an existing ticket/entity ID; the endpoint resolves persisted blueprints in
tenant scope without creating duplicates. The Consultant screen exposes this
as “Run local onboarding walkthrough.” The endpoint never seeds a ticket,
calls an external provider, generates deployment artifacts, or starts a
deployment. Outside that mode it returns a conflict, and a ticket or blueprint
from another tenant is not eligible for the fixture.

The Consultant screen exposes the returned delivery handoff after the
walkthrough completes. It shows the review-only bundle status, target list,
deterministic digest, manifest files, and explicit open items. This is an
operator review handoff, not an official Power Platform solution archive or a
deployment claim; provider packaging, environment evidence, PAC execution, and
approval remain separate requirements.
