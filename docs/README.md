# WAIT Local Agent Documentation

WAIT Local Agent is a local-first AI execution and change-governance runtime.
This index groups the shipped documentation by the path an operator or
contributor is most likely to follow. Capability and provider claims remain
bounded by the current code and the verification notes in the relevant pages.

## Getting started

- [Docker quickstart](getting-started/quickstart-docker.md) — run the Compose appliance.
- [CLI quickstart](getting-started/quickstart-cli.md) — install and exercise the local CLI.
- [Desktop install](getting-started/desktop-install.md) — build and operate the desktop surface.
- [Local demo](getting-started/local-demo.md) — use deterministic local demo data and flows.
- [Configuration](getting-started/configuration.md) — safety flags, authentication, and demo mode.

## Concepts

- [Architecture](concepts/architecture.md) — runtime, provider-neutral consultant layer, and governed execution.
- [Security model](concepts/security-model.md) — local-first security, tenancy, redaction, and threat boundaries.
- [Open-core boundary](concepts/open-core-boundary.md) — Apache 2.0 Community scope and edition framing.
- [Approvals and write gates](concepts/approvals-and-write-gates.md) — draft, review, approval, execution, and audit sequence.

## Connectors

- [Connector matrix](connectors/README.md) — code-derived connector IDs, surfaces, write gates, and fixture/live evidence.
- [HaloPSA setup](connectors/halopsa.md) — PSA safety gates and detailed provider setup.
- [Hudu](connectors/hudu.md) — read-only documentation lookup.
- [IT Glue](connectors/itglue.md) — organization-scoped documentation lookup.
- [Confluence Cloud](connectors/confluence.md) — bounded page reads.
- [Notion](connectors/notion.md) — mapped page/data-source reads and approved comments.
- [SharePoint](connectors/sharepoint.md) — bounded Microsoft Graph site/document reads.
- [Microsoft 365 / Entra](connectors/m365.md) — identity, mailbox, group, license, and device surfaces.
- [ConnectWise PSA](connectors/connectwise.md) — ticket/company reads and approved updates.
- [Syncro](connectors/syncro.md) — ticket/customer reads and approved ticket notes.
- [ServiceNow](connectors/servicenow.md) — incident/company reads and approved metadata actions.
- [Autotask PSA](connectors/autotask.md) — ticket/company reads and approved ticket actions.
- [NinjaOne](connectors/ninjaone.md) — tenant-scoped RMM inventory and approved scripts.
- [Datto RMM](connectors/datto-rmm.md) — mapped RMM inventory and approved quick jobs.
- [N-able N-central](connectors/ncentral.md) — mapped device/issues/tasks and approved direct tasks.
- [N-able N-sight](connectors/nsight.md) — mapped health, backup, antivirus, and patch surfaces.
- [TimeZest](connectors/timezest.md) — mapped scheduling requests and approved create.
- [ScalePad](connectors/scalepad.md) — separately mapped read-only surfaces.
- [Kaseya VSA X](connectors/kaseya-vsa-x.md) — organization-scoped RMM reads and approved scripts.
- [ConnectWise ScreenConnect](connectors/screenconnect.md) — mapped sessions and optional approved commands.
- [AWS permissions](connectors/cloud-permissions-aws.md) — cloud inventory permissions.
- [Azure permissions](connectors/cloud-permissions-azure.md) — cloud inventory permissions.
- [GCP permissions](connectors/cloud-permissions-gcp.md) — cloud inventory permissions.
- [Microsoft 365 cloud permissions](connectors/cloud-permissions-m365.md) — Graph inventory permissions.

## Consultant

- [Consultant lane](consultant/README.md) — discovery, blueprints, governance, and Microsoft targets.
- [Blueprints](consultant/consultant-blueprints.md) — inspectable solution blueprints.
- [Consultant demo](consultant/consultant-demo.md) — deterministic consultant walkthrough.
- [Discovery](consultant/consultant-discovery.md) — bounded discovery intake.
- [Evaluations](consultant/consultant-evaluations.md) — reviewable solution evaluations.
- [Governance](consultant/consultant-governance.md) — governance review surfaces.
- [Monitoring](consultant/consultant-monitoring.md) — tenant-scoped consultant monitoring.
- [Consultant Power Apps](consultant/consultant-power-apps.md) — bounded Power Apps planning.
- [Power Platform deployment](consultant/consultant-power-platform-deployment.md) — reviewable deployment plans.
- [Power Platform package](consultant/consultant-power-platform-package.md) — credential-free source package contract.
- [Supervisor](consultant/consultant-supervisor.md) — bounded delegation plans.
- [Use cases](consultant/consultant-use-cases.md) — read-only Microsoft use cases.
- [Power Apps and Dataverse](consultant/power-apps-dataverse.md) — data/app planning.
- [Power Automate workflows](consultant/power-automate-workflows.md) — workflow planning.
- [Power Platform connectors](consultant/power-platform-connectors.md) — connector preparation.

## Operations

- [Backups and vault](operations/backups-and-vault.md) — local secrets and encrypted state recovery.
- [Scheduling and tenancy](operations/scheduling-and-tenancy.md) — bounded jobs, filters, and tenant scope.
- [Updates](operations/updates.md) — signed update-channel behavior.
- [Host collection](operations/host-collection.md) — explicit host-collection boundary.
- [Work IQ](operations/workiq.md) — Work IQ integration boundary.
- [MSP playbooks](operations/msp-playbooks.md) — governed operational playbooks.
- [Ecosystem integration](operations/ecosystem-integration.md) — integration surfaces and boundaries.
- [Pack loader](operations/pack-loader.md) — installed pack loading and safety.

## Development and reference

- [Release process](development/release-process.md) — release and publication checks.
- [Workflow designer](development/workflow-designer.md) — workflow design surface.
- [CLI reference](reference/cli.md) — code-derived Typer namespace map.
- [API reference](reference/api.md) — route-group overview and running OpenAPI docs.
- [Environment variables](reference/environment-variables.md) — configuration source of truth.
- [MCP reference](reference/mcp.md) — MCP route and policy boundary.

