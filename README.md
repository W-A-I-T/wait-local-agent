<p align="center">
  <img src="desktop/src-tauri/icons/icon.svg" width="120" alt="WAIT Local Agent icon">
</p>

<h1 align="center">WAIT Local Agent</h1>

<p align="center"><em>Local-first AI execution and change governance for real business systems.</em></p>

<p align="center">
  <a href="https://github.com/W-A-I-T/wait-local-agent/actions/workflows/test.yml"><img src="https://github.com/W-A-I-T/wait-local-agent/actions/workflows/test.yml/badge.svg" alt="CI status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/W-A-I-T/wait-local-agent" alt="Apache-2.0 license"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&amp;logoColor=white" alt="Python 3.12 or newer"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-v1.1.1-4c1" alt="Version v1.1.1"></a>
  <a href="docs/README.md"><img src="https://img.shields.io/badge/docs-read_the_docs-536DFE" alt="Documentation"></a>
</p>

## What is WAIT Local Agent?

WAIT Local Agent runs on your own hardware, where your business data and
operational decisions can stay close to you. It connects to the business
systems you already use, including ticketing, documentation, and Microsoft
365. AI can help draft work from local context, while deterministic policy
controls what may happen next. Nothing writes to a live system without
explicit human approval. [Learn the architecture](docs/concepts/architecture.md).

## Screenshots

| Dashboard | Connectors and governed actions |
| --- | --- |
| <img src="docs/media/dashboard.png" alt="WAIT Local Agent dashboard showing local tickets, workflows, and audit activity" width="100%"> | <img src="docs/media/connectors.png" alt="WAIT Local Agent connectors view showing bounded provider surfaces and action controls" width="100%"> |
| Local operations stay visible in one reviewable workspace. | Inspect connector readiness and keep proposed changes behind the approval boundary. |

## Feature highlights

| | |
| --- | --- |
| 🔒 **Local-first**: SQLite, your hardware, and no cloud dependency. [Get started](docs/getting-started/local-demo.md) | ✅ **Approval-gated writes**: review a draft before a live mutation. [See the write gates](docs/concepts/approvals-and-write-gates.md) |
| 🔌 **14 connector entries**: bounded PSA, RMM, documentation, and Microsoft surfaces. [View the matrix](docs/connectors/README.md) | 🏢 **Microsoft 365 and Power Platform consultant lane**: source packages and reviewable plans, not provider deployment. [Explore the lane](docs/consultant/README.md) |
| 🧾 **Audit trail and evidence export**: preserve what happened and why. [Read the security model](docs/concepts/security-model.md) | 👥 **RBAC and tenant scoping**: keep operator permissions and client boundaries explicit. [Read the security model](docs/concepts/security-model.md) |
| 🖥️ **Desktop app, Docker, and CLI**: choose the local surface that fits your team. [Choose an install path](docs/getting-started/quickstart-docker.md) | 🧩 **Open-core packs**: extend the runtime without blurring the public boundary. [Understand editions and packs](docs/concepts/open-core-boundary.md) |

## Architecture

The operator surfaces share one API and one policy path. Connectors do not
become a second execution engine: policy checks scope, role, approval, and
outbound settings before a provider call, then records a bounded result.

```mermaid
flowchart LR
  subgraph Surfaces[Operator surfaces]
    Dashboard["React dashboard :5173"]
    CLI["Typer CLI\nsrc/wait_local_agent/cli.py"]
    Tauri["Tauri desktop"]
  end

  API["FastAPI API :8788\nsrc/wait_local_agent/api/app.py"]
  Policy["Policy layer\nRBAC: rbac.py\napprovals and actions: smart_actions.py\ntenant scope and audit"]
  Store["SQLite store\nsrc/wait_local_agent/store.py"]
  Connectors["Connector adapters\nPSA / RMM / documentation / M365"]
  Packs["Optional pack loader\nsrc/wait_local_agent/api/packs/loader.py"]

  Dashboard --> API
  CLI --> API
  Tauri --> API
  API --> Policy
  Policy --> Store
  Policy -->|writes require approval| Connectors
  Connectors -->|bounded result| Policy
  Packs -.-> API
  style Packs stroke-dasharray: 5 5
```

### What stays in the local runtime

| Part | Job | Default boundary |
| --- | --- | --- |
| Dashboard and desktop | Give an operator a visible workspace. | Served from the local machine. |
| FastAPI and CLI | Accept bounded requests and expose the same runtime services. | Local API on `127.0.0.1:8788` unless you configure otherwise. |
| SQLite store | Keep tickets, drafts, approvals, runs, knowledge, and audit events. | A local file or Docker volume. |
| Connector adapters | Read approved provider surfaces and carry out allowlisted actions. | No outbound call until probing is enabled. |

The normal path is easy to follow: start with local demo data, examine a
draft, review the policy decision, and only then choose whether a provider
connection should be enabled. A team can keep the runtime offline for
documentation, workflow, and audit work, then configure one connector at a
time as its operating practices mature.

The core modules are visible in the repository: `api/app.py` serves the API,
`cli.py` exposes the command line, `rbac.py` and `smart_actions.py` enforce
governed operations, and `store.py` persists local state. The desktop bundle
packages the existing dashboard with the local server sidecar.

## How writes are governed

WAIT starts with a local draft that a human can inspect and edit. Approval is
checked together with the operator role, tenant scope, connector readiness,
and explicit outbound settings. A live mutation also requires
`WAIT_ALLOW_WRITE_ACTIONS=true`; this flag is off by default. Successful and
blocked attempts become local audit events, and provider failures remain
failures rather than being presented as success.

```mermaid
sequenceDiagram
  actor Operator
  participant WAIT
  participant Human as Human reviewer
  participant Gate as Write-gate checks
  participant Connector
  participant Audit

  Operator->>WAIT: create draft
  WAIT-->>Human: reviewable payload
  Human->>WAIT: approve draft
  WAIT->>Gate: check WAIT_ALLOW_WRITE_ACTIONS
  Gate->>Gate: check role, tenant, approval, and probing
  Gate->>Connector: approved connector write
  Connector-->>WAIT: bounded result
  WAIT->>Audit: record audit event
```

![Approval review flow](docs/media/approvals.png)

*The approval queue is the point where a proposed change becomes eligible for
execution; the image is a local demo capture.*

The gate is deliberately repeated at execution time. Editing a draft does not
grant permission, an approval from another tenant cannot be reused, and a
provider response is not treated as evidence of success until the connector
returns a bounded result. This gives reviewers a clear local record even when
an external system is unavailable or rejects the request.

## Quickstart

### Docker

```bash
git clone https://github.com/W-A-I-T/wait-local-agent.git
cd wait-local-agent
docker compose up --build
```

Open the dashboard at `http://127.0.0.1:5173`. The local demo keeps probing,
live writes, cloud fallback, and model inference disabled. [Full guide
→](docs/getting-started/quickstart-docker.md)

### Desktop

Download the installer for your operating system from [GitHub
Releases](https://github.com/W-A-I-T/wait-local-agent/releases). The desktop
bundle runs the dashboard with a local server sidecar. [Full guide
→](docs/getting-started/desktop-install.md)

### CLI

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
wait-local-agent serve
```

For the deterministic, credential-free walkthrough, run
`scripts/demo_appliance.sh` as described in the [Full guide
→](docs/getting-started/local-demo.md).

The CLI and Docker paths use the same local data model. You can start with the
demo, inspect the API and dashboard, and then move to a configured install
without creating a second runtime or migrating your workflow definitions.

## Connectors

The matrix below lists the connector IDs currently returned by the runtime’s
14 `ConnectorStatus` entries. “Yes” means the connector exposes an
approval-gated write surface; “No” means the documented surface is read-only.
All outbound calls still require explicit probing, and every mutation keeps
the write flag and applicable approval checks.

| ID | Connector | Read surface | Approval-gated writes |
| --- | --- | --- | --- |
| `halopsa` | HaloPSA | tickets, notes, clients, assets | Yes |
| `hudu` | Hudu | companies, articles, folders | No |
| `itglue` | IT Glue | organizations, documents, folders | No |
| `confluence` | Confluence Cloud | bounded pages | No |
| `notion` | Notion | mapped pages and data sources | Yes |
| `sharepoint` | SharePoint | sites and document metadata | No |
| `connectwise` | ConnectWise PSA | tickets and companies | Yes |
| `syncro` | Syncro | tickets, comments, customers | Yes |
| `servicenow` | ServiceNow | incidents and companies | Yes |
| `autotask` | Autotask PSA | tickets and companies | Yes |
| `m365` | Microsoft 365 / Entra | users, groups, mail, devices | Yes |
| `timezest` | TimeZest | mapped scheduling requests | Yes |
| `scalepad` | ScalePad | mapped risk and compliance reads | No |
| `rmm` | Configured RMM adapter | bounded NinjaOne, Datto, N-central, N-sight, Kaseya, or ScreenConnect surfaces | Yes |

[See the full connector matrix, setup pages, and fixture/live evidence](docs/connectors/README.md).

Connector rows describe the public contract, not a promise that a provider is
reachable from your network. The matrix marks fixture coverage separately from
live verification, and setup pages explain the credentials and tenant maps
that must be configured locally. Power Platform output follows the same rule:
it is an inspectable source package for a later local operation, not proof of
import or deployment.

## Editions

| Edition | What it means |
| --- | --- |
| **Community** | **C$0 · Apache-2.0 · this repository · self-hosted · genuinely useful, including multi-client use** |
| **Professional** | Commercial packaging and support for teams adopting the local runtime. |
| **MSP** | Commercial packaging and governed operational services for managed service teams. |
| **Enterprise** | Commercial packaging, integration, and assurance support for larger environments. |

Professional, MSP, and Enterprise describe commercial packaging or services;
they do not change the Community license or make multi-client Apache use
conditional on payment. Provider reach and readiness must be verified for the
specific environment. [Read the open-core boundary](docs/concepts/open-core-boundary.md).

## Documentation

- [Getting started](docs/README.md#getting-started): Docker, CLI, desktop, demo, and configuration.
- [Architecture](docs/concepts/architecture.md): runtime layers and provider-neutral design.
- [Approvals and write gates](docs/concepts/approvals-and-write-gates.md): draft, review, approval, execution, and audit.
- [Security model](docs/concepts/security-model.md): safe defaults, tenancy, redaction, and threat boundaries.
- [Connector matrix](docs/connectors/README.md): IDs, read surfaces, writes, and evidence limits.
- [Consultant lane](docs/consultant/README.md): discovery, blueprints, governance, and Microsoft targets.
- [Operations](docs/README.md#operations): backups, scheduling, updates, host collection, and packs.
- [Reference](docs/README.md#development-and-reference): API, CLI, environment variables, and MCP boundaries.

## Safety defaults

> Safety default: fresh installs are read-first and local-first. Live connector writes require `WAIT_ALLOW_WRITE_ACTIONS=true`, outbound connector connection checks must be explicitly enabled, and HaloPSA writes still require an approved draft.

These defaults are part of the product boundary, not a substitute for testing
your own provider configuration. Generated Power Platform output is a
credential-free source package for a later local operation; it is not provider
import, live verification, or deployment evidence.

For a shared installation, add bearer-token roles and a Fernet vault, keep
connector credentials out of action payloads, and review the [configuration
guide](docs/getting-started/configuration.md) before enabling network access.
The [security model](docs/concepts/security-model.md) explains the threat
boundaries, redaction behavior, and tenant-scoped audit trail in more detail.

## Community and contributing

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- Ask questions and share local patterns in [GitHub Discussions](https://github.com/W-A-I-T/wait-local-agent/discussions).
- Report security issues through [SECURITY.md](SECURITY.md), not a public issue.

## License

WAIT Local Agent is released under the Apache License 2.0.
See [LICENSE](LICENSE) for the complete terms.
