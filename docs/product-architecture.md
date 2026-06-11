# WAIT Local Agent — Product Architecture

> Produced: 2026-06-10  
> Based on direct repo inspection + live NeoAgent/competitor research

---

## Why This Product Exists

The MSP AI automation market is dominated by cloud-only services: NeoAgent ($1,000–$2,000/month), Atera Robin, SuperOps Monica, ConnectWise zofiQ, Kaseya Cooper AI, Thread, Rallied, and MSPbots. Every one of these tools requires MSPs to send client tickets, runbooks, and technician decisions to a third-party cloud.

WAIT Local Agent occupies an uncontested category: **local-first, open-source, inspectable AI automation for MSPs and founders**. No client data leaves the operator's hardware by default. No cloud subscription required to run. No vendor to trust with client-sensitive information.

The product serves two personas:

1. **MSP operators** — ticket intelligence, runbook search, PSA workflow drafts, technician approval queue, audit trail, all running on the MSP's own infrastructure.
2. **Startup founders** — project evidence collection, private launch readiness checks, LP preflight, investor evidence preparation, developer handoff — without uploading source code to a SaaS.

---

## Positioning

### Product Name Decisions

| Element | Decision |
|---------|----------|
| Repo name | `wait-local-agent` (keep public, Apache 2.0) |
| Product name | **WAIT Local Agent** |
| MSP paid pack | **WAIT MSP Pack** ($99/month per appliance) |
| Founder paid pack | **WAIT Founder Pack** ($49/month per workspace) |
| Cloud coordination layer | **WAIT Sync** ($29/month) |
| Enterprise hardened edition | **WAIT Agent Appliance** ($499/month) |
| On LP website | **Local Evidence Collector** (Founder Pack add-on framing) |

### Positioning Statement

> "WAIT Local Agent — the open, local AI copilot for MSPs and startup teams. Ticket intelligence, runbook automation, and project evidence — on your hardware, with your rules, without sending every client and project detail to a closed cloud."

### As a Launch Passport Add-On (Founder Mode)

> "Already using WAIT Launch Passport? WAIT Local Agent runs privately on your machine, pre-audits your project against LP's criteria, and exports a signed evidence bundle directly to your LP scan. More confident results, less noise in your $199 audit."

The Founder Pack is the bridge between WAIT Local Agent and WAIT Launch Passport. It is an optional paid add-on to both products.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  WAIT Local Agent — Local-First AI Copilot Appliance             │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │  WAIT MSP Pack   │  │ WAIT Founder Pack│  │  WAIT Sync    │  │
│  │  $99/mo (paid)   │  │  $49/mo (paid)   │  │  $29/mo       │  │
│  │  IT Glue, CW,    │  │  Project scanner │  │  Templates    │  │
│  │  Autotask, M365, │  │  Evidence vault  │  │  Cloud backup │  │
│  │  RMM, QBR, ROI   │  │  LP preflight    │  │  Team sync    │  │
│  └────────┬─────────┘  └────────┬──────────┘  └──────┬────────┘  │
│           │                     │                     │           │
│  ┌────────┴─────────────────────┴─────────────────────┴────────┐  │
│  │          PUBLIC OPEN-SOURCE CORE (Apache 2.0, Free)          │  │
│  │                                                              │  │
│  │  FastAPI REST API · Typer CLI · SQLite FTS5                  │  │
│  │  Approval Engine · Workflow Templates · Provider Abstraction  │  │
│  │  HaloPSA Connector · Hudu Connector                          │  │
│  │  React/Vite Dashboard · Docker Compose · 95% Test Coverage   │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
│                                  │ optional, user-triggered         │
│  ┌───────────────────────────────▼──────────────────────────────┐  │
│  │  WAIT Ecosystem (all connections explicitly opt-in)           │  │
│  │  WAIT Launch Passport · Investor Diligence Passport           │  │
│  │  WAit-Adaptations / AER (via LP escalation only)             │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Product Layer Design

### Layer A — Public Open-Source Core (Apache 2.0, Free)

Everything in the current repo at `W-A-I-T/wait-local-agent`. Full feature list:

| Component | Status | Notes |
|-----------|--------|-------|
| FastAPI REST API (40+ endpoints) | ✓ Built | `src/wait_local_agent/api/app.py` |
| Typer CLI (all command groups) | ✓ Built | `src/wait_local_agent/cli.py` |
| SQLite state store + FTS5 | ✓ Built | `src/wait_local_agent/store.py` |
| Config (35 env vars, safe defaults) | ✓ Built | `src/wait_local_agent/config.py` |
| Knowledge ingestion (.md/.txt/.pdf) | ✓ Built | `src/wait_local_agent/knowledge.py` |
| Optional Docling parser (.docx, OCR) | ✓ Built | guarded import |
| FTS5 keyword search | ✓ Built | `src/wait_local_agent/retrieval.py` |
| Optional Qdrant vector search | ✓ Built | `src/wait_local_agent/vector_search.py` |
| Ticket classification + citation | ✓ Built | `src/wait_local_agent/services.py` |
| Deterministic + Ollama/vLLM providers | ✓ Built | `src/wait_local_agent/providers.py` |
| Approval lifecycle + payload preview | ✓ Built | `src/wait_local_agent/models.py` |
| HaloPSA: read + draft-write + execution | ✓ Built | `src/wait_local_agent/halopsa.py` |
| Hudu: read-only | ✓ Built | `src/wait_local_agent/hudu.py` |
| 5 MSP workflow templates | ✓ Built | `src/wait_local_agent/workflows.py` |
| Docker Compose appliance | ✓ Built | `docker-compose.yml` |
| React/Vite dashboard | ✓ Built | `ui/src/App.tsx` |
| Backup/restore | ✓ Built | `src/wait_local_agent/backup.py` |
| CI/CD (ruff, mypy, bandit, pytest 95%+) | ✓ Built | `.github/workflows/test.yml` |
| API authentication (Bearer token) | Phase 1 | Missing — must fix before promotion |
| Encrypted local secrets (Fernet) | Phase 1 | Missing — must fix before promotion |
| RBAC (admin/technician/viewer) | Phase 2 | Missing |
| Audit export (CSV/JSON) | Phase 2 | Missing |

**Public core rule**: Anything that enables local-only operation, inspection, or automation stays here forever. Integration packs and cloud features are paid.

### Layer B — WAIT MSP Pack ($99/month per appliance, paid proprietary)

Built in private repo `W-A-I-T/wait-local-agent-packs`. Installed as a signed tarball via `wait packs install msp --license <key>`.

Includes:
- IT Glue connector (read-only articles, configurations, assets, organizations)
- ConnectWise PSA connector (read + approval-gated write)
- Autotask PSA connector (read + approval-gated write)
- NinjaOne RMM connector (read-only device inventory, alerts)
- Datto RMM connector (read-only)
- Microsoft 365 / Entra ID read-only (users, groups, MFA status, licenses, applications)
- Scheduled workflow triggers (APScheduler — daily/weekly inactive-ticket follow-up, etc.)
- QBR report generator (per-client PDF: ticket count, resolution rate, top categories, automation savings)
- Automation opportunity report (pattern analysis → "you could automate X")
- Time-saved / ROI dashboard
- Client/tenant boundary enforcement (`client_id` isolation on all queries)
- White-label branding config (`WAIT_PRODUCT_NAME`, logo, color scheme)
- Premium MSP workflow templates (15+ beyond the 5 in open core)

### Layer C — WAIT Founder Pack ($49/month per workspace, paid proprietary)

Built in private repo `W-A-I-T/wait-local-agent-packs`. Installed as signed tarball.

Includes:
- **Project workspace scanner** — reads file tree, manifests, CI presence, route patterns; never reads file contents
- **Evidence vault** — Fernet-encrypted local storage for signed, hashed evidence bundles
- **Launch readiness preflight** — deterministic check against LP claim categories (auth, testing, dependency, deployment, secret); works offline, no LP account needed
- **Developer handoff generator** — structured markdown: architecture summary, dependency list, detected routes, env key inventory, CI setup, gaps, next-steps
- **LP CollectorBundle export** — produces LP-compatible signed JSON bundle from vault artifact
- **LP upload client** — `POST /api/projects/:id/artifacts/collector-bundle` with user-triggered explicit upload + diff preview
- **"Ask my project" assistant** — cited FTS5 Q&A over project docs (README, ADRs, specs, runbooks)
- **Investor evidence preparation workflow** — structured evidence checklist for IDP preparation

### Layer D — WAIT Sync ($29/month, paid)

Optional cloud coordination layer. Requires WAIT Sync backend service (separate roadmap).

Includes:
- Template marketplace — pull workflow template YAML packs
- Encrypted cloud backup — client-side AES-256 before upload; WAIT server cannot read content
- Team / multi-tech coordination — shared approval queue for multiple technicians
- License/entitlement management
- Optional cloud model fallback (Ollama timeout → cloud LLM API with pre-upload redaction)
- Telemetry (opt-in only; aggregated ticket counts, no client data)

### Layer E — WAIT Agent Appliance ($499/month or custom)

Services-led enterprise deployment. Includes all packs + professional hardening:

- Full RBAC setup (scoped tokens per role)
- Vault integration (local Fernet or HashiCorp Vault)
- TLS termination + reverse proxy configuration (Caddy or Nginx)
- Air-gap deployment (fully offline, no external dependencies)
- SLA support + annual update contract
- Deployment and connector setup engagement

---

## MSP Mode Architecture

### Docker Appliance Layout

```
wait-local-agent/
├── docker-compose.yml        ← API + UI services, healthchecks, volumes
├── data/
│   ├── wait.db               ← SQLite state store
│   ├── vault.key.enc         ← Fernet key (Phase 2, chmod 600)
│   ├── secrets.enc           ← Encrypted connector credentials (Phase 2)
│   ├── knowledge/            ← Ingested runbooks and documentation
│   └── backups/              ← Timestamped SQLite backups
├── config/.env               ← Runtime config (no plaintext secrets in Phase 2+)
└── logs/                     ← Structured JSON logs (Phase 2)
```

### Connector Framework

Every connector implements `ConnectorBase`:

```python
class ConnectorBase(Protocol):
    async def health(self) -> ConnectorHealth: ...
    async def list_*(self, ...) -> list[...]: ...     # read operations only
    async def draft_*(self, ...) -> ApprovalRequest: ... # write → creates draft, never executes
```

Execution happens only in `connectors.py` after:
1. `WAIT_ALLOW_HTTP_PROBING=true`
2. `WAIT_ALLOW_WRITE_ACTIONS=true`
3. ApprovalRequest status = `approved`

### RBAC Model (Phase 2)

| Role | Approve queue | Read all | Configure connectors | Manage RBAC | Export audit |
|------|--------------|---------|---------------------|-------------|-------------|
| **Admin** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Technician** | ✓ (own queue) | ✓ | ✗ | ✗ | ✓ (own events) |
| **Viewer** | ✗ | ✓ | ✗ | ✗ | ✗ |

Roles encoded in scoped API tokens: `WAIT_ADMIN_TOKEN`, `WAIT_TECH_TOKEN`, `WAIT_VIEWER_TOKEN`.

### Connector Roadmap

| Connector | Phase | Read | Write | Tier |
|-----------|-------|------|-------|------|
| HaloPSA | Done | ✓ full | ✓ gated | Public core |
| Hudu | Done | ✓ full | — | Public core |
| IT Glue | Phase 3 | ✓ | — first | MSP Pack |
| ConnectWise PSA | Phase 4 | ✓ | ✓ gated | MSP Pack |
| Autotask | Phase 4 | ✓ | ✓ gated | MSP Pack |
| NinjaOne RMM | Phase 4 | ✓ inventory | — | MSP Pack |
| Datto RMM | Phase 4 | ✓ inventory | — | MSP Pack |
| M365 / Entra | Phase 4 | ✓ read-only | — first | MSP Pack |
| SharePoint | Phase 4 | ✓ docs | — | MSP Pack |
| N-able | Phase 5 | ✓ | — | MSP Pack |
| Kaseya VSA | Phase 5 | ✓ | — | MSP Pack |
| Slack / Teams | Phase 5 | ✓ | ✓ gated | MSP Pack |
| ServiceNow | Phase 7 | ✓ | ✓ gated | Appliance |

---

## Founder Mode Architecture

### How Founder Mode Differs from MSP Mode

| Dimension | MSP Mode | Founder Mode |
|-----------|----------|-------------|
| Primary data source | PSA ticket queue | Local project directory |
| Primary output | Ticket summaries, PSA workflow drafts | Readiness findings, evidence bundles |
| Connectors | HaloPSA, Hudu, RMM, M365 | Repo scanner, doc vault, LP upload client |
| Approval queue | PSA write approvals | Evidence bundle upload approval |
| Knowledge base | Client runbooks, IT procedures | Project specs, ADRs, READMEs, docs |
| Report type | Technician log, QBR | LP preflight, developer handoff |
| Cloud connection | Never (MSP data stays local) | Optional LP upload (founder explicit opt-in) |
| LP relationship | None | Pre-LP private audit lane |

### Founder Journey

```
1. Founder runs WAIT Local Agent (free/open core) locally:
   - Ingests project docs into knowledge base
   - Asks "what auth does my project use?" — cited answer
   
2. Founder installs WAIT Founder Pack ($49/month):
   wait founder scan /path/to/project         → CollectorBundle in vault
   wait founder preflight                      → local readiness report
   wait founder handoff --output handoff.md    → developer handoff doc

3. When ready for LP ($199 scan):
   wait founder export-bundle --output b.json  → review what will be sent
   wait founder upload --lp-project-id <id>    → explicit upload to LP

4. LP scans the bundle + any other evidence:
   → LaunchPassportReport with readiness score, findings, blockers

5. (Optional) Founder purchases IDP Technical Add-on ($999):
   → IDP imports LP investor pack markdown
   → Investor Diligence Report + PDF
```

### Evidence Vault Design

```
vault_artifacts table:
  id TEXT PRIMARY KEY
  project_id TEXT
  created_at TEXT (ISO 8601)
  bundle_hash TEXT (SHA-256)
  signature TEXT (HMAC-SHA-256 with vault key)
  bundle_json_enc BLOB (Fernet encrypted)
  metadata JSON
```

Bundle signing:
```python
bundle_bytes = json.dumps(bundle, sort_keys=True).encode("utf-8")
bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()
# vault_key from Fernet-encrypted vault.key.enc (never transmitted)
signature = hmac.new(vault_key[:32], bundle_hash.encode(), "sha256").hexdigest()
```

---

## Security and Safety Model

### Safe-by-Default Flags (current `config.py`)

| Flag | Default | Meaning |
|------|---------|---------|
| `WAIT_ALLOW_HTTP_PROBING` | `false` | No outbound HTTP to PSA/RMM |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | No live connector writes |
| `WAIT_ALLOW_LLM_INFERENCE` | `false` | Deterministic provider only |
| `WAIT_ALLOW_CLOUD_FALLBACK` | `false` | No cloud model calls |
| `WAIT_ALLOW_OCR` | `false` | No OCR processing |

All must be explicitly set `true` by the operator. Even then, writes require an approved ApprovalRequest. No action is ever automatic.

### Threat Model

| Threat | Mitigation |
|--------|-----------|
| Unauthenticated API (current gap) | Phase 1: Bearer token middleware on all routes |
| Compromised connector token | Approval gate + payload preview; write lock flags |
| Prompt injection from ticket body | Structured delimiters in prompts; deterministic by default; all model output goes to approval queue |
| Unsafe automation | Two-flag lock (probing + write) + human approval; zero auto-execution |
| Cross-client data leakage | Phase 3: `client_id` enforcement on all ticket/knowledge queries |
| Accidental cloud upload | Explicit user trigger + diff preview; no background sync ever |
| Poisoned documentation | Path validation (`_validate_allowed_path`); no code execution from KB |
| Bad model output | All model outputs are drafts; human approval required before execution |
| Destructive M365/RMM action | Read-only first in all new connectors; writes only after Phase 4 + approval |
| Malicious local user | Immutable audit trail; Phase 2: approver identity logged in events |
| Plaintext connector secrets | Phase 1: Fernet-encrypted vault replaces env-only secret storage |

---

## Local Model and AI Policy

### Provider Priority Order

1. **Deterministic** (default): keyword classification + template substitution + FTS5 citation — always works, always reproducible
2. **Local OpenAI-compatible** (opt-in: `WAIT_ALLOW_LLM_INFERENCE=true`): Ollama/vLLM at `WAIT_OPENAI_BASE_URL`
3. **Cloud fallback** (disabled by default: `WAIT_ALLOW_CLOUD_FALLBACK=true`): redaction pass before any cloud call

### Cited-Answers-Only Policy

- Every knowledge-based response includes `sources: [{doc_path, chunk_id, snippet}]`
- If no relevant sources found: response is "No relevant documentation found for this query"
- Model cannot invent evidence; all claims must trace to a source chunk in the knowledge base
- Model outputs are always drafts; none are executed without explicit human approval

### Prompt-Injection Protection

- User-supplied content wrapped in structural delimiters: `<ticket_body>...</ticket_body>`
- Model instructed to ignore instructions found inside ticket content
- All model output enters the approval queue; never immediate execution
- Deterministic mode is immune to prompt injection by design
