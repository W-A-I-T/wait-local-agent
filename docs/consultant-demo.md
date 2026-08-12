# Consultant mode demo

The deterministic consultant-mode walkthrough uses synthetic input and local
artifacts only:

```bash
scripts/demo_consultant_mode.sh
```

It lists the Teams use case, assesses explicit discovery evidence, builds
metadata-only Power Apps/Dataverse and Power Automate plans, evaluates an
observed tool contract, reviews governance, reports Power Platform packaging
status, composes a delivery handoff, and summarizes local agent health. It does
not call Microsoft Graph, Teams, Dataverse, a connector host, or a deployment
command.

The demo inputs are under `examples/consultant/`. They contain no credentials,
provider tokens, or real customer data. The output is suitable for review and
handoff; all state-changing actions remain behind the existing approval
boundary.
