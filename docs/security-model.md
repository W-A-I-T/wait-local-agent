# Security Model

> WAIT Local Agent is designed to be safe by default. All potentially dangerous capabilities require explicit operator opt-in and are disabled in fresh installs.

---

## Safe-by-Default Flags

Every flag defaults to `false`. The operator must consciously choose to enable each one.

| Flag | Default | Required for |
|------|---------|-------------|
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Any outbound HTTP to PSA/RMM/KB systems |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Live writes to any connector (creates tickets, notes, etc.) |
| `WAIT_ALLOW_LLM_INFERENCE` | `false` | Local model calls (Ollama/vLLM) |
| `WAIT_ALLOW_CLOUD_FALLBACK` | `false` | Cloud model calls when local model times out |
| `WAIT_ALLOW_OCR` | `false` | OCR processing of scanned documents |

**Live writes require all three to be true**: `WAIT_ALLOW_HTTP_PROBING=true` AND `WAIT_ALLOW_WRITE_ACTIONS=true` AND an approved `ApprovalRequest` record.

---

## Authentication (Phase 1)

**Current state (Phase 1 — must fix before public promotion)**:

The API has no authentication middleware. Any caller on the local network can invoke all endpoints. This is acceptable for a single-operator local demo but is not safe for multi-user MSP deployment.

**Phase 1 fix**:

- Add `WAIT_API_TOKEN` config (empty = demo mode, no auth required)
- Add `WAIT_DEMO_MODE=true` default (explicit local-only mode)
- Add Bearer token middleware (`security.py`) on all routes
- When `WAIT_API_TOKEN` is set and `WAIT_DEMO_MODE=false`, all requests require `Authorization: Bearer {token}`
- Unauthenticated requests return `HTTP 401`

**Phase 2 extension** (RBAC):

Three scoped tokens — `WAIT_ADMIN_TOKEN`, `WAIT_TECH_TOKEN`, `WAIT_VIEWER_TOKEN`:

| Role | Approve queue | Read all | Configure connectors | Manage RBAC | Export audit |
|------|--------------|---------|---------------------|-------------|-------------|
| **Admin** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Technician** | ✓ (own queue) | ✓ | ✗ | ✗ | ✓ (own events) |
| **Viewer** | ✗ | ✓ | ✗ | ✗ | ✗ |

---

## Secrets Management (Phase 1)

**Current state**: Connector credentials (`WAIT_HALOPSA_CLIENT_SECRET`, `WAIT_HUDU_API_KEY`, etc.) are stored in environment variables. This means secrets may appear in Docker logs, shell history, `.env` files committed accidentally, or process listings.

**Phase 1 fix**:

- Add `WAIT_SECRETS_BACKEND=env|fernet` config
- Add `WAIT_VAULT_PATH=data/vault` config
- Create `vault.py`: Fernet-encrypted local secrets store
  - `wait secrets init` — generates vault key, stores at `data/vault.key.enc` (chmod 600)
  - `wait secrets set HALOPSA_CLIENT_SECRET <value>` — encrypts and stores
  - `wait secrets list` — shows key names only, never values
- Connector credential loading: check vault first, fall back to env if `WAIT_SECRETS_BACKEND=env`
- Document: backup the vault key; loss of vault key = permanent loss of stored secrets

**Operator responsibility**: The operator must ensure `data/vault.key.enc` is not committed to version control and is backed up separately from the database.

---

## Payload Redaction

The `_redact_payload()` function in `api/app.py` strips sensitive keys from approval request payloads before returning them to the client.

**Current coverage** (expand in Phase 1):
- `secret`, `token`, `api_key`, `password`

**Expanded coverage** (Phase 1):
- Add: `apikey`, `auth_token`, `bearer`, `authorization`, `x-api-key`, `client_secret`, `access_token`

Redaction is applied on all approval request reads. Stored execution results do not contain raw secrets — only sanitized metadata (action type, HTTP status code, remote ID, result message).

---

## Approval Gate Design

Every connector write follows this path — no shortcuts:

```
1. draft_*(ticket_id, action_type, fields) → ApprovalRequest (status=pending)
2. Technician reviews payload in UI or CLI
3. Technician optionally edits "fields" key (only; action_type and ticket_id locked)
4. Technician approves with comment (comment persisted, approver identity in Phase 2)
5. execute_*_approval_request(request_id) checks:
   - WAIT_ALLOW_HTTP_PROBING=true
   - WAIT_ALLOW_WRITE_ACTIONS=true
   - request.status == "approved"
6. PSA API call made
7. Audit event written: request_id, action_type, payload_hash, result, http_status, timestamp
8. No retry on failure without a new approval cycle
```

There is no code path that executes a write without going through steps 1–7.

---

## Audit Trail

All side effects are written to the immutable `event_history` table. The table is append-only; no update or delete operations exist on it.

Each event records: `event_type`, `entity_type`, `entity_id`, `description`, `metadata_json`, `created_at`.

Phase 2 adds `approver_id` (SHA-256 hash of the approving token — pseudonymous, not plaintext) to approval events.

Phase 2 also adds `GET /audit-events/export?format=csv|json&from=&to=` for compliance reporting.

---

## Knowledge Base Safety

Document ingestion is restricted by `WAIT_ALLOWED_DOC_ROOT`. The `_validate_allowed_path()` function in `knowledge.py`:

1. Resolves the full absolute path (follows symlinks)
2. Verifies the resolved path is under `WAIT_ALLOWED_DOC_ROOT` via `Path.relative_to()`
3. Rejects paths that escape the root (directory traversal, symlink attacks)

No code in ingested documents is executed. Documents are parsed as text only (Markdown, plain text, PDF text extraction, optional Docling parsing — never `exec`, `eval`, or subprocess).

---

## Threat Model

| Threat | Risk Level | Mitigation | Phase |
|--------|-----------|-----------|-------|
| Unauthenticated API | High (must fix) | Bearer token middleware | Phase 1 |
| Plaintext connector secrets | High (must fix) | Fernet-encrypted vault | Phase 1 |
| Prompt injection from ticket body | Medium | Structured delimiters; deterministic by default; approval queue | Always |
| Unsafe automation (auto-execute) | High | Two-flag lock + human approval required; no auto-execution code path | Always |
| Cross-client data leakage | Medium (Phase 3+) | `client_id` enforcement on all queries | Phase 3 |
| Accidental cloud upload (Founder) | Low | Explicit user trigger + diff preview; no background sync | Phase 4 |
| Poisoned documentation | Low | Path validation; no code execution from KB | Always |
| Bad model output executed | Medium | All model outputs are drafts; human approval required | Always |
| Destructive M365/RMM write | Medium (Phase 4+) | Read-only first; writes only after approval + flag | Phase 4 |
| Malicious local user bypassing approval | Low | Immutable audit trail; Phase 2 approver identity logging | Phase 2 |
| Secrets in environment variables | High (current) | Fernet vault replaces env secrets in Phase 1 | Phase 1 |
| Rate limiting / DoS via connector | Low | `slowapi` rate limiting added in Phase 2 | Phase 2 |
| Compromised connector token | Medium | Approval gate still required; write flags can be disabled immediately | Always |

---

## Pre-Promotion Security Checklist

These items must be complete before actively promoting the public repo:

- [ ] `gitleaks detect --source . --log-opts HEAD` — no secrets in git history
- [ ] `pip-audit` clean — no critical CVEs
- [ ] `pip-licenses` — all deps Apache 2.0 or MIT
- [ ] API authentication implemented (Phase 1)
- [ ] Fernet secrets vault implemented (Phase 1)
- [ ] Redaction expansion to cover all key variants (Phase 1)
- [ ] `SECURITY.md` updated with auth setup and vault setup guidance
- [ ] Live-write disclaimer prominently in README: "Live PSA writes require explicit opt-in, human approval, and approved flags — they are never enabled by default"
- [ ] All existing tests updated to include auth headers (Phase 1)
- [ ] New auth + vault tests passing (Phase 1)
