# Microsoft consultant use-case catalog

The read-only catalog at `GET /consultant/use-cases` gives technicians a
bounded starting point for common Microsoft-oriented engagements. It covers
M365 onboarding, Teams service-desk triage, SharePoint knowledge retrieval,
Power Apps/Dataverse approval workspaces, and multi-agent service-desk
supervision.

Filter by category when needed:

```text
GET /consultant/use-cases?category=teams
```

The equivalent local command is:

```bash
wait-local-agent microsoft use-cases list --category teams
```

Catalog entries describe suggested services, agent roles, review outputs, and
approval boundaries. They are not executable workflows, do not contain tenant
data or credentials, and report `execution_started: false` and
`deployment_started: false`. A selected use case must still pass the tenant
scoping, connector, evaluation, governance, and approval surfaces before any
state-changing operation is considered.
