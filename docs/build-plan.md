# Build Plan — Phases 0–8

> Phased implementation plan for WAIT Local Agent from current Phase 1 beta to commercial launch.
> Produced: 2026-06-10 based on direct repo inspection.

---

## Current State Summary

The repo is at Phase 1 beta ("Sellable Local Ticket Copilot"). What is fully built:

- FastAPI REST API (40+ endpoints), Typer CLI, SQLite state store + FTS5
- HaloPSA connector (read + draft-write + execution), Hudu connector (read-only)
- 5 workflow templates, approval queue, knowledge ingestion, document parsing
- Deterministic + Ollama/vLLM provider abstraction
- React/Vite dashboard, Docker Compose appliance, backup/restore
- CI/CD: ruff, mypy, bandit, pip-audit, pytest 95%+ coverage, UI build

**Phase 1 blockers** (must fix before public promotion):
1. No API authentication — any LAN caller can invoke all endpoints including HaloPSA writes
2. No encrypted secrets — connector credentials in plaintext env vars
3. Redaction gaps — `_redact_payload()` misses `apikey`, `auth_token`, `bearer` key variants

---

## Phase 0 — Repo Truth Audit and Product Decision Record

**Goal**: Confirm CI is green, Docker demo works end-to-end, no secrets in git history, all deps compatible. Lock product decisions.

**Tasks** (complete before writing any new code):
1. Run `gitleaks detect --source . --log-opts HEAD` on full git history — confirm zero hits
2. Run `pip-audit` and `bandit -r src/` on current HEAD — confirm no critical findings
3. Start `docker compose up`, run `scripts/demo_appliance.sh` — confirm end-to-end pass
4. Run `pip-licenses` — confirm all deps are Apache 2.0 or MIT
5. Write `docs/product-decision-record.md` committing to: product name, layer structure, Apache 2.0 for core, proprietary for packs, two-repo strategy
6. Update `docs/status.md` with commercial readiness assessment

**Files changed**: `docs/product-decision-record.md` (new), `docs/status.md` (updated)

**Exit criteria**: CI green, no secrets in history, Docker demo passes, product decision record committed.

**Not yet**: No new features, no code changes.

---

## Phase 1 — API Authentication + Encrypted Secrets

**Goal**: Make the repo safe to promote publicly. Two safety blockers resolved.

### Task 1.1 — Bearer Token Middleware

Create `src/wait_local_agent/security.py`:
```python
class TokenAuth(HTTPBearer): ...

async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings: Settings = Depends(get_settings)
) -> str:
    # Compare against settings.api_token; raise HTTPException(401) if wrong
    # Skip auth when settings.demo_mode=true and api_token is empty

async def require_demo_or_auth() -> str:
    # In demo mode (api_token empty): allow all requests
    # Otherwise: require valid token
```

Update `config.py`: add `WAIT_API_TOKEN: str = ""` and `WAIT_DEMO_MODE: bool = True`.

Update `api/app.py`: add `dependencies=[Depends(require_auth)]` to all state-mutating routes; `Depends(require_demo_or_auth)` to read routes.

Update `.env.example`: document `WAIT_API_TOKEN` with comment explaining demo vs production mode.

### Task 1.2 — Fernet-Encrypted Local Secrets Vault

Create `src/wait_local_agent/vault.py`:
```python
class SecretVault:
    @staticmethod
    def initialize(vault_path: Path) -> "SecretVault":
        # Generate Fernet key, save to vault_path/vault.key.enc (chmod 600)

    def set(self, key: str, value: str) -> None:
        # Encrypt value, write to vault_path/secrets.enc (JSON map)

    def get(self, key: str) -> str | None:
        # Load and decrypt secrets.enc, return value for key

    def list_keys(self) -> list[str]:
        # Return key names only — never values
```

Update `config.py`: add `WAIT_SECRETS_BACKEND: str = "env"` (options: `env`, `fernet`) and `WAIT_VAULT_PATH: str = "data/vault"`.

Update `cli.py`: add `wait secrets` command group:
- `wait secrets init` — generate vault key
- `wait secrets set <KEY> <VALUE>` — store encrypted
- `wait secrets list` — show key names
- `wait secrets get <KEY>` — decrypt and print (admin only in Phase 2)

Update `halopsa.py` and `hudu.py`: load credentials via `SecretVault.get()` when `WAIT_SECRETS_BACKEND=fernet`, fall back to env when `env`.

### Task 1.3 — Redaction Expansion

Update `_redact_payload()` in `api/app.py`: extend pattern to match:
`secret`, `token`, `api_key`, `password`, `apikey`, `auth_token`, `bearer`, `authorization`, `x-api-key`, `client_secret`, `access_token`

### Task 1.4 — README Rewrite + Release Tag

Rewrite `README.md` with new public positioning (see `docs/product-architecture.md`).
Update `SECURITY.md` with auth setup and vault setup sections.
Tag `v1.0.0-beta` on main.

**Files changed**: `security.py` (new), `vault.py` (new), `config.py` (+4 settings), `api/app.py` (auth deps + redaction), `cli.py` (secrets group), `halopsa.py`, `hudu.py`, `.env.example`, `README.md`, `SECURITY.md`, `tests/test_security.py` (new), `tests/test_vault.py` (new)

**Tests**:
- `test_security.py::test_missing_token_returns_401`
- `test_security.py::test_wrong_token_returns_401`
- `test_security.py::test_correct_token_returns_200`
- `test_security.py::test_demo_mode_allows_no_token`
- `test_security.py::test_redact_apikey_variant`
- `test_security.py::test_redact_auth_token_variant`
- `test_security.py::test_redact_bearer_variant`
- `test_vault.py::test_fernet_round_trip`
- `test_vault.py::test_list_keys_shows_no_values`
- `test_vault.py::test_vault_get_set_round_trip`
- `test_vault.py::test_missing_key_returns_none`
- All existing API test fixtures updated with `Authorization: Bearer test-token` header

**Risks**: Existing test fixtures fail until auth headers added; coordinate test updates with code changes.

**Exit criteria**: CI green; `curl localhost:8000/tickets` → 401 when token set; `wait secrets set` + `list` works; Docker demo passes with `WAIT_API_TOKEN=demo-token`.

**Not yet**: RBAC, multi-tenant, new connectors.

---

## Phase 2 — Local Appliance Hardening

**Goal**: Production-grade security. Any MSP team can deploy this confidently.

### Task 2.1 — RBAC

Create `src/wait_local_agent/rbac.py`:
```python
class Role(Enum):
    ADMIN = "admin"
    TECHNICIAN = "technician"
    VIEWER = "viewer"

async def require_role(role: Role) -> Callable:
    # FastAPI dependency factory; validates token against WAIT_{ROLE}_TOKEN env
```

Update `config.py`: add `WAIT_ADMIN_TOKEN`, `WAIT_TECH_TOKEN`, `WAIT_VIEWER_TOKEN`.

Update `api/app.py`: add role-specific dependencies to write routes (POST/PATCH require TECHNICIAN+; connector config requires ADMIN).

Update `ui/src/App.tsx`: hide write buttons for viewer tokens; hide config panel for non-admin.

### Task 2.2 — Approver Identity in Audit

Update `store.py`: migration adding `approver_id TEXT` column to `approval_requests` and `audit_events`.

Update `api/app.py`: on approval, set `approver_id = sha256(token)[:16]` (pseudonym).

### Task 2.3 — Audit Export Route

Add `GET /audit-events/export` to `api/app.py`:
- Query params: `format=csv|json`, `from=ISO8601`, `to=ISO8601`, `client_id=` (optional)
- Returns streamed CSV or JSON array
- Requires ADMIN role

### Task 2.4 — Encrypted Backup

Update `backup.py`: add `backup_encrypted(dest: Path, vault: SecretVault)` — Fernet-encrypts DB before writing.

Update CLI: `wait backup --encrypt` and `wait restore --encrypted <file>`.

### Task 2.5 — Connector Credential Validation

Add `wait connectors validate halopsa` and `wait connectors validate hudu` CLI commands: call `health()` and report success/failure before operator configures credentials for real.

### Task 2.6 — Rate Limiting

Add `slowapi` to `pyproject.toml`. Add `@limiter.limit("100/minute")` to all routes; `@limiter.limit("10/minute")` to connector-triggering routes.

**Files changed**: `rbac.py` (new), `config.py` (+3 tokens), `api/app.py` (RBAC deps, audit export, rate limits), `store.py` (migration), `backup.py` (encrypted option), `cli.py` (connectors validate), `ui/src/App.tsx` (role-aware), `pyproject.toml` (slowapi), `tests/test_rbac.py` (new), `tests/test_audit_export.py` (new), `tests/test_backup.py` (updated)

**Tests**:
- `test_rbac.py::test_viewer_cannot_approve_request`
- `test_rbac.py::test_viewer_cannot_post_workflow`
- `test_rbac.py::test_technician_can_approve`
- `test_rbac.py::test_technician_cannot_configure_connector`
- `test_rbac.py::test_admin_can_do_all`
- `test_audit_export.py::test_export_returns_csv`
- `test_audit_export.py::test_export_date_filter_works`
- `test_audit_export.py::test_viewer_cannot_export`
- `test_backup.py::test_encrypted_backup_decrypt_round_trip`

**Exit criteria**: Three-role auth working; audit export tested; encrypted backup round-trip confirmed.

**Not yet**: New connectors, scheduled workflows, multi-tenant.

---

## Phase 3 — MSP Sellable MVP

**Goal**: A real MSP can install, connect HaloPSA + IT Glue, triage tickets, run weekly automated follow-ups, and produce a QBR report.

Note: Phase 3 paid connector code (IT Glue, QBR) goes in `W-A-I-T/wait-local-agent-packs` (private). The public repo gets the connector framework updates and APScheduler integration.

### Task 3.1 — IT Glue Connector (private repo: packs/msp/itglue.py)

```python
class ITGlueConnector:
    # Auth: X-API-KEY header
    async def health(self) -> ConnectorHealth: ...
    async def list_organizations(self) -> list[ITGlueOrg]: ...
    async def list_configurations(self, filter_org: str | None) -> list[ITGlueConfig]: ...
    async def list_articles(self, filter_org: str | None) -> list[ITGlueArticle]: ...
    async def get_article(self, article_id: int) -> ITGlueArticle: ...
    # Read-only in Phase 3; no write surface
    # Rate limit: 10 req/sec; add asyncio.sleep(0.1) between batch calls
```

### Task 3.2 — Scheduled Workflows (public repo)

Create `src/wait_local_agent/scheduler.py`:
```python
class SchedulerManager:
    def start(self) -> None:  # Called on app startup; uses APScheduler AsyncIOScheduler
    def register(self, template_id: str, cron: str, params: dict) -> ScheduledJob: ...
    def list_jobs(self) -> list[ScheduledJob]: ...
    def pause(self, job_id: str) -> None: ...
    def resume(self, job_id: str) -> None: ...
```

Add `scheduled_jobs` table to `store.py` (migration). Persists across restarts.

Each trigger creates a `WorkflowRun` → same approval path as manual trigger.

Add routes: `GET /scheduled-jobs`, `POST /scheduled-jobs`, `DELETE /scheduled-jobs/:id`.

### Task 3.3 — `client_id` on All Data (public repo)

Migration: add `client_id TEXT` (nullable) to `tickets`, `approval_requests`, `audit_events`, `knowledge_documents`, `workflow_runs`.

All list routes: accept `?client_id=` filter. Default: return all (backward compatible).

### Task 3.4 — QBR Report Generator (private repo: packs/msp/reports/qbr.py)

```python
class QBRReportBuilder:
    def build(self, client_id: str, period_start: date, period_end: date) -> QBRReport:
        # Collects: ticket count by category, resolution rate, workflow automation count,
        # top KB articles cited, avg. resolution time, time saved estimate
        # Output: JSON + PDF (fpdf2)
```

Route: `GET /reports/qbr?client_id=&period_start=&period_end=&format=json|pdf`

### Task 3.5 — Onboarding Wizard (public repo)

Add `ui/src/components/OnboardingWizard.tsx` — 5-step setup UI:
1. Choose PSA (HaloPSA / ConnectWise / IT Glue / HaloPSA + IT Glue)
2. Enter credentials + test connection
3. Configure knowledge base path
4. Run ingest — progress bar
5. Run demo ticket — show result

Show on first load when no connector is configured.

### Task 3.6 — Install Script (public repo)

Create `scripts/install.sh`:
- Checks: Docker v24+, Compose v2+, `curl`, `openssl`
- Pulls `ghcr.io/w-a-i-t/wait-local-agent:latest`
- Generates `.env` with random `WAIT_API_TOKEN`
- Runs `docker compose up -d`
- Prints: "Open http://localhost:3000 — admin token: <token>"

Create `scripts/upgrade.sh`: pulls latest image + restart + runs migrations.

**Exit criteria**: MSP can install via `install.sh`, connect HaloPSA + IT Glue, ingest runbooks, triage tickets, schedule weekly follow-up, export QBR PDF for a client.

**Not yet**: ConnectWise, Autotask, M365, RMM, Founder Pack.

---

## Phase 4 — Connector Expansion + Founder Pack

**Goal**: Full MSP connector suite; Startup/Founder Pack built and working.

Note: All paid connectors go in `wait-local-agent-packs`. Founder Pack code goes in `wait-local-agent-packs/packs/founder/`. CLI commands and API routes go in the public repo.

### Task 4.1 — ConnectWise PSA Connector (private repo)

```python
class ConnectWiseConnector:
    # Auth: Client ID + HMAC-SHA256 (ConnectWise Manage API v2021.1)
    async def health(self) -> ConnectorHealth: ...
    async def list_tickets(self, status: str | None, company_id: int | None, page: int): ...
    async def get_ticket(self, ticket_id: int): ...
    async def list_companies(self): ...
    async def list_board_statuses(self, board_id: int): ...
    async def draft_note(self, ticket_id, text, internal: bool) -> ApprovalRequest: ...
    async def draft_status_update(self, ticket_id, status_id) -> ApprovalRequest: ...
```

Execution: `execute_connectwise_approval_request()` in `connectors.py`.

### Task 4.2 — Autotask PSA Connector (private repo)

```python
class AutotaskConnector:
    # Auth: API user + integration key (Base64 header)
    async def health(self) -> ConnectorHealth: ...
    async def list_tickets(self, filter_params: dict): ...
    async def get_ticket(self, ticket_id: int): ...
    async def list_accounts(self): ...
    async def draft_note(self, ticket_id, note_text, is_internal: bool) -> ApprovalRequest: ...
```

### Task 4.3 — M365 / Entra Read-Only Connector (private repo)

```python
class M365Connector:
    # Auth: OAuth2 client credentials (MSAL)
    # Required app permissions: User.Read.All, Group.Read.All, Organization.Read.All
    async def health(self) -> ConnectorHealth: ...
    async def list_users(self, filter: str | None): ...
    async def get_user_mfa_status(self, user_id: str): ...
    async def list_groups(self): ...
    async def list_applications(self): ...
    # Read-only in Phase 4
```

Config: `WAIT_M365_TENANT_ID`, `WAIT_M365_CLIENT_ID`, `WAIT_M365_CLIENT_SECRET`.

Docs: `docs/connectors/m365-setup.md` — MSAL app registration guide.

### Task 4.4 — NinjaOne RMM Read-Only Connector (private repo)

```python
class NinjaOneConnector:
    # Auth: OAuth2 client credentials (NinjaOne API v2)
    async def health(self) -> ConnectorHealth: ...
    async def list_devices(self, organization_id: int | None): ...
    async def get_device(self, device_id: int): ...
    async def list_organizations(self): ...
    async def list_alerts(self, device_id: int | None): ...
    # Read-only in Phase 4
```

### Task 4.5 — Founder Pack (private repo: packs/founder/)

**Scanner** (`scanner.py`):
```python
class ProjectScanner:
    def scan(self, project_root: Path) -> CollectorBundle:
        # Reads: file tree (paths+sizes, no contents), package manifests,
        # CI workflow count, test framework detection, route patterns (regex),
        # gitleaks findings (type+path+severity, no secret values),
        # env key names (from .env.example only, never .env)
        # Returns: CollectorBundle-compatible JSON
```

**Evidence Vault** (`vault.py`):
```python
class EvidenceVault:
    def store(self, bundle: CollectorBundle) -> VaultEntry: ...
    def list(self) -> list[VaultEntry]: ...
    def get(self, artifact_id: str) -> CollectorBundle: ...
    def export(self, artifact_id: str, output_path: Path) -> None: ...
```

**Preflight** (`preflight.py`):
```python
class LaunchPreflight:
    def run(self, bundle: CollectorBundle) -> PreflightReport:
        # Deterministic checks (no LLM):
        # - Has tests? - Has CI? - Secret leak risk?
        # - Dependency vulnerabilities? - Auth patterns?
        # - Env config? - README? - License?
        # Maps each check to LP claim categories
        # Returns: PreflightReport with checks, readiness_score, recommendations
```

**Handoff Generator** (`handoff.py`):
```python
class HandoffGenerator:
    def generate(self, bundle: CollectorBundle, kb_docs: list[str]) -> str:
        # Returns structured Markdown:
        # architecture summary, dependency list, routes, env key inventory,
        # CI setup, test status, known gaps, next-steps checklist
```

**LP Upload Client** (`lp_client.py`):
```python
class LPClient:
    async def get_upload_token(self) -> str: ...
    async def upload_bundle(self, bundle: CollectorBundle) -> UploadResult: ...
    async def get_scan_status(self, scan_id: str) -> str: ...
```

CLI (public repo): add `wait founder` command group:
- `wait founder scan <path>`
- `wait founder preflight`
- `wait founder handoff --output handoff.md`
- `wait founder export-bundle --artifact-id <id> --output bundle.json`
- `wait founder upload --artifact-id <id>`

API routes (public repo): `GET /founder/vault`, `POST /founder/scan`, `GET /founder/preflight/latest`, `POST /founder/upload/:artifact_id`

**Tests**:
- `test_founder_scanner.py::test_scan_produces_valid_collector_bundle`
- `test_founder_scanner.py::test_scan_includes_no_file_contents`
- `test_founder_scanner.py::test_scan_includes_no_secret_values`
- `test_founder_vault.py::test_store_and_retrieve_round_trip`
- `test_founder_vault.py::test_bundle_hash_matches_on_retrieve`
- `test_founder_preflight.py::test_project_with_tests_passes_check`
- `test_founder_preflight.py::test_project_without_ci_warns`
- `test_founder_lp_client.py::test_upload_sends_bundle_to_lp_mock`
- `test_founder_lp_client.py::test_no_source_code_in_upload_payload`
- `test_m365.py::test_read_only_no_write_surface`

**Exit criteria**: Founder can scan project, run preflight, generate handoff doc, export bundle, optionally upload to LP. ConnectWise and Autotask pass mock tests.

**Not yet**: WAIT Sync, template marketplace, Autotask advanced writes.

---

## Phase 5 — WAIT Ecosystem Bundle Integration

**Goal**: LP upload fully wired; bundle validator; pre-upload diff preview; `wait doctor` reports LP status.

### Task 5.1 — Bundle Validator (private repo: packs/founder/)

```python
class BundleValidator:
    def validate(self, bundle: CollectorBundle) -> ValidationResult:
        # Checks: sourceCode==false, no absolute paths,
        # no env values (keys only), signature verification, hash match
        # Returns: ValidationResult with violations list
        # Upload blocked on any critical violation
```

### Task 5.2 — Pre-Upload Diff Viewer (public repo API)

Add `GET /founder/upload-preview/:artifact_id`:
- Returns: file count, finding types (no values), route count, env key names, what LP will receive
- Never shows: file contents, secret values
- Required before upload button is clickable in dashboard

### Task 5.3 — LP Connection Health (public repo)

Add `GET /founder/lp-status`:
- Returns: `{connected: bool, project_id, last_upload, last_scan_status}`
- Update `wait doctor` to show LP connection status

### Task 5.4 — Upload Token Refresh (private repo)

Auto-refresh LP upload token before expiry. Store last token + expiry in `founder_config` SQLite table.

**Tests**:
- `test_bundle_validator.py::test_bundle_with_source_code_fails_validation`
- `test_bundle_validator.py::test_bundle_with_absolute_paths_fails_validation`
- `test_bundle_validator.py::test_valid_bundle_passes`
- `test_lp_integration.py::test_upload_bundle_schema_matches_lp`
- `test_lp_integration.py::test_upload_token_refresh_on_expiry`

**Exit criteria**: `wait founder upload` shows diff preview, requires confirmation, uploads, shows scan status. `wait doctor` reports LP status.

---

## Phase 6 — WAIT Sync (Optional Cloud Coordination)

**Prerequisite**: WAIT Sync backend service must exist (separate roadmap; out of scope here).

**Goal**: Add opt-in paid cloud layer for template sync, encrypted backup, and team coordination.

**Tasks**:
1. Create `src/wait_local_agent/sync/client.py` — WAIT Sync REST API client
2. Template pull: `wait sync pull-templates` — download connector packs
3. Encrypted cloud backup: `wait sync backup` — client-side AES-256 (WAIT server sees only ciphertext)
4. License check: `wait sync status` — validates MSP Pack or Founder Pack entitlement
5. Team coordination: shared approval queue via Sync relay for multi-technician setups
6. Optional cloud model fallback: `WAIT_ALLOW_CLOUD_FALLBACK=true` + Ollama timeout → Claude API + redaction
7. Telemetry: `WAIT_TELEMETRY_ENABLED=false` by default; opt-in sends aggregated ticket counts only

**Exit criteria**: Template packs downloadable; cloud backup verified to be opaque to WAIT server; license gate working.

---

## Phase 7 — Paid Packs + Enterprise Hardening

**Goal**: MSP Pack and Founder Pack packaged as installable, licensed tarballs. Enterprise Appliance tier.

**Tasks**:
1. Package `packs/msp/` tarball (Phase 3–4 connector code + templates + report generators)
2. Package `packs/founder/` tarball (Phase 4–5 vault + scanner + LP client)
3. HMAC-signed offline license key system (validates without WAIT Sync)
4. Feature gating: `pack_enabled("msp")` check before executing any paid feature
5. White-label branding: `WAIT_PRODUCT_NAME`, `WAIT_BRAND_LOGO_URL`
6. N-able RMM connector (read-only)
7. Kaseya VSA connector (read-only)
8. Enterprise hardening guide: TLS, reverse proxy, HashiCorp Vault integration

**Exit criteria**: `wait packs install msp --license <key>` installs and gates correctly; white-label branding configurable; N-able + Kaseya pass mock tests.

---

## Phase 8 — Launch, Docs, Pricing, Sales Assets

**Goal**: Everything needed for a public launch that converts MSPs and founders.

**Tasks**:
1. Final README rewrite with architecture diagram (Mermaid), screenshots, demo GIF
2. Demo data in `demo/`: sample runbooks, sample tickets (not real client data)
3. Demo script: 5-minute walkthrough from `docker compose up` to first approved HaloPSA note
4. Demo video (screen recording)
5. `CHANGELOG.md` with release history
6. GitHub issue templates: bug, connector request, workflow template request, security
7. `CONTRIBUTING.md` update: how to write a connector, PR requirements
8. `scripts/install.sh` and `scripts/upgrade.sh` finalized and tested on Ubuntu 22.04 + macOS
9. `gitleaks detect` clean, `pip-audit` clean, `pip-licenses` all Apache 2.0/MIT
10. Release tag `v1.0.0` on main
11. WAIT website: landing page with pricing, demo, install path
12. CI badge + license badge on README

**Exit criteria**: `curl .../install.sh | bash` → running appliance in < 5 minutes; README readable to first-time MSP visitor.

---

## What to Build First (Phase 1 only)

1. `src/wait_local_agent/security.py` — Bearer token middleware
2. `src/wait_local_agent/vault.py` — Fernet encrypted secrets vault
3. Updated `README.md` with new public positioning
4. Release tag `v1.0.0-beta`

## What to Defer

- WAIT Sync (no backend yet; design doc only in Phase 6)
- Scheduled workflows (Phase 3)
- ConnectWise / Autotask (Phase 4)
- Founder Pack (Phase 4)
- QBR PDF (Phase 3)
- Multi-tenant enforcement (Phase 3)

## What NOT to Delete or Simplify

Nothing in the current codebase is dead weight. Keep `backup.py` as `shutil.copy` until Phase 2 adds encryption. Keep workflow templates as deterministic strings until Phase 4 branching is needed.
