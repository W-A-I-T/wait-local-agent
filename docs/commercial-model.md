# Commercial Model

> Pricing, go-to-market strategy, open-core licensing, and competitive positioning.

---

## Pricing Tiers

| Tier | Price | What's included |
|------|-------|----------------|
| **Open Core** | Free (Apache 2.0) | Full runtime, HaloPSA + Hudu connectors, 5 workflow templates, approval queue, knowledge base, Docker Compose, 95%+ test suite |
| **WAIT MSP Pack** | $99/month per appliance | + IT Glue, ConnectWise, Autotask, NinjaOne, Datto, M365/Entra connectors; scheduled workflows; QBR report PDF; ROI/time-saved dashboard; automation opportunity report; client/tenant boundaries; white-label branding; 15+ premium templates |
| **WAIT Founder Pack** | $49/month per workspace | + Project workspace scanner; encrypted evidence vault; launch readiness preflight; LP CollectorBundle export + upload; developer handoff generator; investor evidence preparation |
| **WAIT Sync** | $29/month | + Template marketplace; encrypted cloud backup (client-side AES-256); multi-tech team coordination; license management; optional cloud model fallback |
| **WAIT Agent Appliance** | $499/month or custom | + All packs; RBAC setup; Vault integration; TLS + reverse proxy config; air-gap deployment; SLA support; annual updates |
| **Deployment / Hardening** | $1,500–$5,000 one-time | Professional installation, connector setup, workflow customization, security hardening |
| **Custom Connector** | $2,500–$7,500 | New PSA/RMM/ITSM connector built to spec, tested, maintained for 12 months |
| **Annual Support** | $1,200/year | Priority support, version upgrades, connector updates |

---

## Price Comparison Against Competitors

| Scenario | Competitor | Competitor Price | WAIT Local Agent | Annual Saving |
|----------|-----------|-----------------|-----------------|---------------|
| Solo MSP, HaloPSA triage | NeoAgent Starter | $1,000/mo | Free (open core) | $12,000/year |
| MSP with ConnectWise + IT Glue + M365 | NeoAgent Growth | $1,500/mo | $99/mo (MSP Pack) | $17,412/year |
| MSP with Atera (5 technicians) | Atera Pro | $645/mo (5 × $129) | $99/mo (MSP Pack) | $6,552/year |
| MSP with SuperOps (5 technicians) | SuperOps Pro | $745/mo (5 × $149) | $99/mo (MSP Pack) | $7,752/year |
| Privacy/self-hosted required | Any cloud tool | Not available | $99–$499/mo | Only option |
| MSP, team coordination + templates | NeoAgent + tooling | $1,000+/mo | $99+$29/mo = $128/mo | $10,464+/year |
| Startup founder pre-LP | None | N/A | $49/mo | New market |
| Enterprise air-gap | None | Not available | $499/mo + services | Only option |

**Where WAIT should be cheaper**: Entry-level MSP automation; privacy-sensitive clients; self-hosted preference; teams locked out of cloud.

**Where WAIT should be premium**: Professional deployment and hardening (services-led); enterprise air-gap; custom connectors.

**Where services-led sales makes sense**: Enterprise Appliance ($499+/month), multi-site MSP deployments, custom automation packs, compliance engagements (HIPAA, FedRAMP).

---

## Open-Core Licensing Strategy

| Component | License | Rationale |
|-----------|---------|-----------|
| Core runtime, CLI, store, approval engine | Apache 2.0 | Inspectable, commercially safe, community-friendly |
| HaloPSA + Hudu connectors | Apache 2.0 | Reference implementations; community can contribute fixes |
| Connector base protocol | Apache 2.0 | Encourages community connectors |
| Workflow template schema | Apache 2.0 | Community can contribute templates |
| MSP Pack connectors (IT Glue, ConnectWise, M365, RMM) | Proprietary (WAIT-Tech) | Revenue lever; distributed as signed tarball via WAIT Sync |
| Founder Pack (vault, scanner, LP client) | Proprietary (WAIT-Tech) | Revenue lever |
| WAIT Sync client | Proprietary | Cloud features require paid subscription |
| White-label branding configs | Proprietary | MSP reseller feature |

**AGPL contamination prevention**: Every dependency added must be checked with `pip-licenses` before merge. `alga-psa` (AGPL, referenced in roadmap as architecture reference) must never have code copied into this repo. LangGraph (MIT), Qdrant (Apache 2.0), Docling (MIT), APScheduler (MIT), and MSAL (MIT) are all safe.

---

## Repo Strategy (Public vs Private)

Two repos are needed for the open-core model:

| Repo | Visibility | License | Contents |
|------|-----------|---------|---------|
| `W-A-I-T/wait-local-agent` | **Public** | Apache 2.0 | Open core: runtime, CLI, store, HaloPSA+Hudu, templates, dashboard, tests, docs, connector framework |
| `W-A-I-T/wait-local-agent-packs` | **Private** | Proprietary | MSP Pack + Founder Pack + WAIT Sync client |

The public repo contains the pack loader interface (`packs/loader.py`) and the connector base protocol. Pack code never appears in the public repo.

Pack installation:
```bash
wait packs install msp --license <license-key>
# Downloads signed tarball from WAIT Sync or direct URL
# Validates HMAC signature against WAIT's embedded public key
# Extracts to ./packs/msp/  (gitignored)
# License checked on each startup (offline HMAC or WAIT Sync validation)
```

**Create `wait-local-agent-packs`** when starting Phase 3 (IT Glue connector is the first private piece). Phases 1–2 are entirely public core work.

---

## Go-to-Market Strategy

### Ideal Customer Profiles

**ICP 1: Privacy-first MSP** (primary wedge)
- 5–50 person shop; uses HaloPSA or ConnectWise; has Hudu or IT Glue
- Handles 200–2,000 tickets/month
- Has clients in regulated industries (healthcare, legal, finance)
- Cannot tell clients "your tickets go to Azure"
- Budget-conscious; NeoAgent at $1,000+/month is too expensive

**ICP 2: Solo/bootstrapped founder** (Founder Pack)
- B2B SaaS founder, solo or 2–3 person team
- Preparing for launch or seed fundraising
- Wants WAIT Launch Passport audit but wants private pre-audit lane first
- Wants a local AI assistant for their project without SaaS data risk

**ICP 3: Enterprise IT with air-gap requirement** (Appliance tier)
- Government, healthcare, defense contractor
- Cannot use any cloud tool regardless of pricing
- Currently using manual runbooks or Rewst with heavy engineering

### First Wedge

**HaloPSA + local ticket triage** — built, free, works in 30 minutes:

> "WAIT Local Agent for HaloPSA — ticket summaries, runbook citations, and approval-gated notes. Runs on your server. Never sends a ticket to Azure."

No new features needed for this wedge. Phase 1 safety fixes (auth + vault) enable safe promotion.

### Launch Sequence

1. Phase 1 complete → soft launch to beta MSPs and test users
2. Phase 2 complete (RBAC + audit export) → public repo promotion
3. Announce: r/msp, MSPGeek Discord, HaloPSA community forums, r/sysadmin, Hacker News ("Show HN: Local-first MSP AI copilot — Apache 2.0, runs on your Docker")
4. Blog post: "Why we built a local-first MSP AI copilot instead of another cloud SaaS"
5. Phase 3 complete → MSP Pack launch at $99/month
6. Landing page with pricing + demo GIF or YouTube video
7. Phase 4 complete → Founder Pack launch + LP cross-promotion on LP dashboard

### Positioning Against Cloud Competitors

Do not name cloud competitors in README headings or hero copy. Use category framing:

- "local-first MSP AI copilot" is a distinct category
- Emphasize what cloud tools cannot offer: self-hosted, open-source, startup mode, evidence bundles, air-gap
- SEO keywords: "self-hosted MSP AI", "local MSP automation", "HaloPSA AI copilot", "open source MSP copilot", "MSP AI privacy"
- When asked directly: "Cloud tools are great for teams comfortable with that model. WAIT Local Agent is for teams that are not."

### Content Strategy

- "5 reasons to run your MSP AI copilot locally" (privacy, inspection, cost, air-gap, trust)
- "From ticket to approved HaloPSA note: the WAIT Local Agent approval workflow"
- "How founders use WAIT Local Agent to prepare for LP audits without uploading source code"
- "Building a local knowledge base from your MSP runbooks in 10 minutes"
- "WAIT Local Agent vs NeoAgent: local-first vs cloud-first for MSP ticket automation"
- "Why ConnectWise/Kaseya AI lock-in is a risk for growing MSPs"

### Channel Strategy

- Phase 8: apply for Pax8/Ingram Micro listing (after MSP Pack is stable)
- HaloPSA community partnership (HaloPSA app marketplace / integration listing)
- MSPGeek community sponsorship
- WAIT Adaptation services as channel: managed deployment for MSPs who want white-glove setup
