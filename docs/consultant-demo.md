# Consultant mode demo

The deterministic consultant-mode walkthrough uses synthetic input and local
artifacts only:

```bash
scripts/demo_consultant_mode.sh
```

It lists the Teams use case, assesses explicit discovery evidence, builds a
reviewable Power Apps/Dataverse artifact manifest and Power Automate plan, prepares a
review-only OpenAPI custom-connector package and Copilot Studio handoff, prints a staged `pac solution`
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
The result reports environment verification and governance as review gates when
external credentials are absent, records local supervisor/evaluation evidence,
and explicitly leaves artifact generation, live provider execution, and
deployment unstarted.
