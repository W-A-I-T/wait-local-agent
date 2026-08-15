# CLI Reference

The 37 CLI registrations below are derived from the `add_typer` calls in
`src/wait_local_agent/cli.py`. Nested names are shown with their full command
path.

| Namespace | Purpose and representative commands |
| --- | --- |
| `tickets` | Ticket intelligence; `tickets summarize TCK-1002`. |
| `audit` | Audit listing/export; `audit list`, `audit export`. |
| `knowledge` | Local knowledge operations; `knowledge ingest`. |
| `connectors` | Connector status, reads, drafts, and executions; `connectors list`, `connectors validate halopsa`. |
| `workflows` | Templates, runs, and gallery; `workflows templates`, `workflows run ...`. |
| `consultant` | Local-first consultant commands. |
| `consultant blueprints` | Inspectable blueprints; `consultant blueprints ...`. |
| `microsoft` | Microsoft platform preparation commands. |
| `microsoft connector` | Metadata-only Power Platform connector commands. |
| `microsoft provider` | Bounded model-provider health; `microsoft provider health`. |
| `microsoft solution` | Reviewable Power Platform solution plans. |
| `microsoft evaluation` | Bounded consultant evaluations. |
| `microsoft governance` | Review-only governance evaluations. |
| `microsoft monitoring` | Tenant-scoped consultant health summaries. |
| `microsoft power-apps` | Bounded Power Apps/Dataverse plans and build artifacts. |
| `microsoft use-cases` | Read-only Microsoft consultant use cases. |
| `microsoft workflow` | Review-only Power Automate plans. |
| `microsoft copilot-studio` | Review-only Copilot Studio handoffs. |
| `microsoft discovery` | Bounded consultant discovery intake. |
| `microsoft supervisor` | Tenant-scoped supervisor delegation plans. |
| `microsoft delivery` | Review-only consultant delivery handoffs. |
| `microsoft package` | Deterministic local Power Platform YAML source packages. |
| `approvals` | Approval queue review; `approvals list`, `approvals update ID approved`. |
| `events` | Event history; `events list`. |
| `backup` | SQLite backup/restore. |
| `hardening` | Appliance hardening checks. |
| `secrets` | Local Fernet vault operations; `secrets init`, `secrets list`. |
| `update` | Signed update-channel operations; `update check`. |
| `packs` | Installed pack operations; `packs status`. |
| `founder` | Founder-surface commands. |
| `reports` | Stored report list/detail/export and scheduling. |
| `collectors` | Collector protocol operations. |
| `collectors bundle` | Collector evidence bundles. |
| `smart-actions` | Bounded action catalog, invocation, and runs. |
| `executions` | Execution observability. |
| `analytics` | Execution analytics. |
| `agents` | Bounded agent definitions and runs. |

The root app also exposes commands such as `doctor`, `ingest`, and
`technician-chat`. Provider-specific connector commands are registered under
`connectors`; they do not bypass the outbound, write, role, tenancy, or
approval boundaries.
