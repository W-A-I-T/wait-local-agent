# Competitive Analysis — WAIT Local Agent

> Research date: 2026-06-10  
> Sources: neoagent.io (live fetch), Capterra, search results, guardz.com, rallied.ai, getthread.com

> Current-code note: the competitor facts and market observations below retain
> their original research snapshot. WAIT capability rows are maintained against
> the current public core; bounded read, preview, and approval-gated support is
> not equivalent to full provider parity.

---

## Market Category Map

The MSP AI automation market in 2026 divides into four categories:

| Category | Tools | Characteristics |
|----------|-------|----------------|
| **Rule-based RPA** | Rewst, Microsoft Power Automate | Deterministic, requires developer setup, high maintenance |
| **Bundled PSA/RMM AI** | Atera+Robin, SuperOps+Monica, ConnectWise+zofiQ, Kaseya Cooper AI, NinjaOne AI, HaloPSA AI | AI baked into existing management platform — locked to vendor |
| **Standalone cloud AI agent** | NeoAgent, Thread, Rallied, MSPbots, Mizo | Cloud-only automation layer on top of existing PSA/RMM |
| **Local/self-hosted** | **WAIT Local Agent** | **New category — currently uncontested** |

---

## Full Competitor Table

| Product | Category | Price | PSA/RMM | Deployment | Self-hosted | Open source | Approval | WAIT advantage |
|---------|----------|-------|---------|-----------|-------------|-------------|---------|----------------|
| **NeoAgent** | Standalone AI agent | $1,000–$2,000/mo | HaloPSA, ConnectWise, Autotask, ServiceNow; NinjaOne, Datto, N-able, Kaseya; IT Glue, Hudu; M365 Entra | Cloud (Azure) | ✗ | ✗ | Optional | Privacy, local, open, price |
| **Atera + Robin** | Bundled PSA/RMM | $129–$209/tech/mo | Bundled (own PSA+RMM) | Cloud SaaS | ✗ | ✗ | Autonomous L1 | PSA-agnostic; local; no per-tech lock |
| **SuperOps + Monica** | Bundled PSA/RMM | $89–$179/tech/mo + $3/endpoint | Bundled (own PSA+RMM); agentic marketplace | Cloud SaaS | ✗ | ✗ | Agentic auto | PSA-agnostic; local; no per-endpoint charge |
| **ConnectWise + zofiQ** | Bundled PSA (acquired Jan 2026) | Enterprise (contact) | ConnectWise PSA + RMM only | Cloud SaaS | ✗ | ✗ | Human-in-loop | Works with HaloPSA/Autotask; not CW-only |
| **Kaseya Cooper AI** | Bundled RMM/PSA | Kaseya 365 bundle | Kaseya ecosystem only | Cloud SaaS | ✗ | ✗ | Automated + review | PSA-agnostic; not locked to Kaseya |
| **Thread** | Standalone AI agent | Not public | HaloPSA, ConnectWise, Autotask | Cloud SaaS | ✗ | ✗ | Autonomous for 10-25% | Local-first; inspectable; price |
| **Rallied** | Standalone AI agent | Not public | Any (API-based) | Cloud SaaS | ✗ | ✗ | Autonomous L1 | Privacy; local; open-source |
| **MSPbots** | Standalone AI agent | $399–$1,799/mo | ConnectWise, Autotask, HaloPSA | Cloud SaaS | ✗ | ✗ | Bot + approvals | Price; local; open-source |
| **Mizo** | AI triage entry | <$250/mo entry | ConnectWise, Autotask | Cloud SaaS | ✗ | ✗ | Human reviews all | Full workflow, not just triage |
| **Rewst** | Rule-based RPA | Not public (high) | Any with REST API | Cloud (hybrid scripting) | Partial | ✗ | Explicit rule-defined | No developer required; deterministic built-in |
| **WAIT Local Agent** | **Local-first open agent** | **Open core; pack pricing not established in this repo** | HaloPSA, Hudu, ConnectWise, Autotask, ServiceNow, IT Glue, Confluence, SharePoint, bounded M365, NinjaOne, Datto, and N-central capabilities | **Self-hosted Docker** | **✓** | **✓ Apache 2.0** | **Approval required for supported writes; reads and analysis are non-mutating** | **Local, inspectable, bounded** |

---

## NeoAgent Deep Comparison (Primary Cloud Competitor)

NeoAgent is the market leader in the standalone MSP AI agent category. Understanding where it wins and where WAIT Local Agent wins is essential for positioning.

### NeoAgent Facts (source: neoagent.io, 2026-06-10)

- **Price**: $1,000 Starter (3,000 tickets/month) / $1,500 Growth / $2,000 Professional
- **Model**: 1 ticket = 1 credit; credits available as add-ons
- **Deployment**: Cloud-only, Microsoft Azure; no self-hosted option
- **PSA**: ConnectWise PSA, Autotask, HaloPSA, ServiceNow
- **RMM**: NinjaOne, Datto RMM, N-able, ConnectWise RMM variants, Kaseya
- **Documentation**: IT Glue, Hudu
- **Identity**: Microsoft Entra ID, on-prem AD/Exchange
- **Comms**: Slack, Microsoft Teams
- **Distribution**: Pax8, D&H, Sherweb, Ingram Micro
- **Approval model**: Technician-in-the-loop (review before execution) OR autonomous for low-risk tasks — technician's choice
- **Security**: SOC 2 Type I certified; Type II in progress; per-tenant isolation; no model training on client data
- **Trial**: 14-day free trial, no credit card required
- **Setup**: "Live in two hours"

### Gap Table

| Capability | NeoAgent | WAIT Local Agent (has) | WAIT missing | Build priority |
|-----------|----------|----------------------|-------------|----------------|
| HaloPSA read + gated write | ✓ | ✓ (`halopsa.py`) | — | Done |
| Hudu read | ✓ | ✓ (`hudu.py`) | — | Done |
| ConnectWise PSA | ✓ | ✓ bounded reads + approval-gated allowlisted ticket updates | Deeper write/action parity | Incremental |
| Autotask | ✓ | ✓ ticket/company inventory plus approval-gated ticket-note/time-entry/status/resolution/assignment updates | Broader write operations | Incremental |
| ServiceNow | ✓ | ✓ incident/company inventory plus approval-gated work-note/state/assignment updates | Broader write operations | Incremental |
| NinjaOne RMM | ✓ | ✓ bounded devices, alerts, scripts, previews, and approved execution | Broader remediation parity | Incremental |
| Datto RMM | ✓ | ✓ bounded devices, alerts, components, and approved quick jobs | Broader remediation parity | Incremental |
| N-able | ✓ | ✓ N-central read-only device/issue/task metadata | Execution and richer remediation | Incremental |
| Kaseya | ✓ | ✗ | Connector | Phase 5 |
| IT Glue | ✓ | ✓ read-only organization/document retrieval | Broader search and write operations | Incremental |
| M365 / Entra | ✓ | ✓ bounded reads plus approved user, group, license, session, Intune, mailbox-settings, and message mutations | Broader resource and policy coverage | Incremental |
| Slack / Teams | ✓ | ✓ preview and configured webhook delivery paths | Native provider features and delivery receipts | Incremental |
| Scheduled / proactive tasks | ✓ | ✓ (bounded cron + event agents) | Broader recurrence and event sources | Phase 3 |
| QBR / ROI reporting | ✓ | Bounded client-scoped QBR and automation-opportunity reports from local evidence | Provider-backed lifecycle enrichment, measured ROI, and PDF export | Incremental |
| Pax8 / distribution channel | ✓ | ✗ | GTM work | Phase 8 |
| SOC 2 certification | ✓ (Type I) | ✗ | Compliance work | Phase 7+ |
| **Self-hosted / on-prem** | ✗ | **✓ Docker Compose** | — | **Core win** |
| **Privacy (no data leaves)** | ✗ | **✓ by design** | — | **Core win** |
| **Open-source inspectable** | ✗ | **✓ Apache 2.0** | — | **Core win** |
| **Air-gap compatible** | ✗ | **✓ local core can run offline** | Cloud connector features require connectivity | **Local-core win** |
| **Startup/founder mode** | ✗ | **Public API/CLI contract; private pack not included** | Full founder pack implementation | Separate pack work |
| **LP evidence export** | ✗ | ✗ (planned) | Build Phase 5 | WAIT ecosystem |
| **Price** | $1,000–$2,000/mo | **Open core; public pack pricing not established** | Commercial pricing and support model | GTM work |

### Where WAIT Wins Against NeoAgent

1. **Privacy**: The local core can keep client data on the MSP's appliance by default; configured external connectors are explicit opt-ins.
2. **Open-source**: MSPs and enterprise clients can read every line. No black box.
3. **Air-gap**: Core local workflows can run offline; external connector operations are unavailable without connectivity.
4. **Price**: The open core has no public pack price in this repository; commercial savings are not claimed here.
5. **Startup/founder mode**: The public repository defines the Founder API/CLI boundary while the private pack remains separate.
6. **PSA-agnostic**: Works with HaloPSA, ConnectWise, Autotask, and others — not locked to one vendor ecosystem.

### Where NeoAgent Wins

1. **Integration breadth**: Wider provider depth, native actions, and hosted integrations in several areas; WAIT's current support remains bounded and local-first.
2. **Distribution**: Pax8, Ingram Micro, Sherweb channel partnerships.
3. **SOC 2**: Type I certified; Type II in progress.
4. **Setup speed**: "Live in two hours" vs. self-hosted Docker install.
5. **Autonomous resolution**: Teams can set low-risk tickets to auto-execute (WAIT requires approval by design).

---

## Bundled Platform Competitors

### Atera + Robin AI

- **Price**: $129–$209/technician/month
- **Model**: Robin resolves L1 issues around the clock autonomously; technician reviews L2+
- **Weakness**: PSA/RMM locked to Atera ecosystem; not available for HaloPSA-only MSPs
- **WAIT advantage**: PSA-agnostic; local-first; open-source; no per-technician pricing model

### SuperOps + Monica AI

- **Price**: $89–$179/tech/month + $3/endpoint/month
- **Model**: Monica is the agentic AI layer embedded across the platform; agentic marketplace launched in 2025
- **Weakness**: Locked to SuperOps ecosystem; per-endpoint pricing adds up
- **WAIT advantage**: PSA-agnostic; no per-endpoint charge; local-first; inspectable

### ConnectWise + zofiQ (acquired January 2026)

- **Price**: Enterprise pricing (contact)
- **Model**: Deep integration across ConnectWise PSA and RMM — best for full ConnectWise shops
- **Weakness**: Exclusively ConnectWise ecosystem; enterprise pricing; not available for HaloPSA/Autotask shops
- **WAIT advantage**: Works with HaloPSA, Autotask, ConnectWise; local-first; open-source

### Kaseya Cooper AI

- **Price**: Bundled in Kaseya 365
- **Model**: AI across the entire Kaseya ecosystem (VSA, BMS, IT Glue integration)
- **Weakness**: Locked to Kaseya ecosystem; forces full platform adoption
- **WAIT advantage**: PSA-agnostic; local; does not require platform migration

---

## Rule-Based RPA Competitor

### Rewst

- **Price**: Not public (high; requires vendor conversation)
- **Model**: Most powerful RPA for MSPs; full workflow builder with branching, loops, and integrations; requires developer skills to configure
- **Weakness**: Significant setup engineering effort; not "plug in and go"
- **WAIT advantage**: No developer required for deterministic workflows; WAIT Local Agent's templates work out of the box

---

## Positioning Summary

WAIT Local Agent should never position itself as "NeoAgent but cheaper." The correct framing is a **new category**:

> "Local-first, open-source MSP AI copilot — for teams where client data sovereignty is non-negotiable."

MSPs who are comfortable with Azure can use NeoAgent, Atera, or SuperOps. MSPs who are not — and there are many — currently have no option. WAIT Local Agent is their only option.

The secondary market (startup founders) has no competitor at all. This is a completely new use case with no incumbent.
