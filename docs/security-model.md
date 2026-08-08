# Security Model

WAIT Local Agent is designed to be safe by default. Potentially dangerous capabilities require explicit operator opt-in and are disabled in fresh installs.

## Safe-by-default flags

| Flag | Default | Required for |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Outbound HTTP calls to PSA, RMM, or knowledge systems |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Live connector mutations |
| `WAIT_ALLOW_LLM_INFERENCE` | `false` | Local model calls |
| `WAIT_ALLOW_CLOUD_FALLBACK` | `false` | Cloud model calls after local timeout |
| `WAIT_ALLOW_OCR` | `false` | OCR processing of scanned documents |
| `WAIT_END_USER_SUPPORT_ENABLED` | `false` | Optional scoped end-user ticket routes |

HaloPSA live writes require all of the following: `WAIT_ALLOW_HTTP_PROBING=true`, `WAIT_ALLOW_WRITE_ACTIONS=true`, complete connector credentials, and an approved `ApprovalRequest` record.

NinjaOne RMM calls use the same outbound HTTP gate. A tenant/client request is
accepted only when its ID resolves through the operator-controlled
`WAIT_NINJAONE_ORGANIZATION_MAP_JSON`; provider IDs and credentials are not
request-supplied authorization inputs. Inventory and execution lookup apply
returned-row scope checks. Script execution additionally requires
`WAIT_ALLOW_WRITE_ACTIONS=true` and a completed technician approval.

## API authentication

Current implementation:

- `WAIT_DEMO_MODE=true` and empty `WAIT_API_TOKEN` keeps the local demo path open.
- Setting `WAIT_DEMO_MODE=false` requires `WAIT_API_TOKEN`.
- Any configured token requires `Authorization: Bearer <token>` for API requests.
- Missing or invalid tokens return HTTP 401.

Production-like local installs should set:

```text
WAIT_DEMO_MODE=false
WAIT_API_TOKEN=<strong-local-token>
```

End-user support requires a separate token and explicit fixed scope:

```text
WAIT_END_USER_SUPPORT_ENABLED=true
WAIT_END_USER_TOKEN=<end-user-token>
WAIT_END_USER_CLIENT_ID=<client-id>
WAIT_END_USER_USER_ID=<requester-id>
```

The end-user token is not a technician or admin token. It cannot select a
tenant in the request, invoke smart actions, or read tickets belonging to a
different requester.

## Secrets management

Current implementation supports two backends:

| Backend | Setting | Notes |
| --- | --- | --- |
| Environment | `WAIT_SECRETS_BACKEND=env` | Default for demo and Docker Compose simplicity |
| Fernet vault | `WAIT_SECRETS_BACKEND=fernet` | Local encrypted file store under `WAIT_VAULT_PATH` |

Vault commands:

```bash
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
wait-local-agent secrets list
```

`secrets list` prints names only. `secrets get` prints a value for local operator recovery and should be treated as sensitive terminal output.

Operators must back up the vault key separately. Losing `vault.key` means stored secrets cannot be decrypted.

## Payload redaction

Approval request API views redact sensitive key variants before returning payloads to the client. Covered key fragments include:

```text
secret, token, api_key, password, apikey, auth_token, bearer, authorization, x-api-key, client_secret, access_token
```

Redaction recurses through nested dictionaries and lists. Stored execution results contain sanitized metadata only.

## Approval gate design

Every HaloPSA write follows this path:

```text
1. draft_* creates an ApprovalRequest with status=pending.
2. Technician reviews payload in the UI or CLI.
3. Technician may edit only the fields payload while pending.
4. Technician approves or rejects with a comment.
5. Execution checks connector, action type, ticket id, approval status, flags, and prior execution state.
6. PSA API call is made only after the checks pass.
7. Audit and event history rows are written.
8. A succeeded approval cannot be executed again.
```

Pending approval requests receive a bounded 24-hour deadline. Reading the queue
or attempting a mutation expires overdue requests, records the expiration and a
system actor in audit history, rejects any linked pending workflow or smart
action run, and blocks edits, approval, and connector execution. Existing
pending rows are assigned the same deadline during schema migration; expiration
is intentionally not operator-disableable in this release.

An agent definition may shorten that deadline for its approval-required tools;
the override is validated, capped at 30 days, and never extends the tool-level
approval policy.

Scheduled jobs accept only validated IANA timezone names. Existing rows migrate
to `UTC`; schedule timezones affect trigger interpretation but do not change
tenant scope, approval policy, or connector authorization.

Event-delivery retries require technician access and the original tenant scope.
They are capped at three attempts and target only failed or dependency-blocked
agents recorded for that delivery. Successful agent attempts are not replayed;
retry payloads remain internal and delivery views use the existing redaction
policy.

Hudu is read-only in the public repo.

## Audit trail and export

The event history table is append-only through application code. It records event type, subject id, status, message, payload JSON, and timestamp.

API export:

```bash
curl http://127.0.0.1:8788/audit/export
curl 'http://127.0.0.1:8788/audit/export?export_format=csv'
```

CLI export:

```bash
wait-local-agent audit export .wait-local-agent/audit.json
wait-local-agent audit export .wait-local-agent/audit.csv --format csv
```

## Knowledge base safety

Document ingestion is restricted by `WAIT_ALLOWED_DOC_ROOT`. The ingestion service resolves the full path and rejects paths outside the configured root. Ingested documents are parsed as text; no document code is executed.

## Threat model summary

| Threat | Mitigation | Status |
| --- | --- | --- |
| Unauthenticated shared API | Bearer token gate outside demo mode | Implemented |
| Plaintext local connector secrets | Optional Fernet vault | Implemented |
| Unsafe connector mutation | Two flags plus human approval | Implemented |
| Credential leakage in approval views | Expanded recursive redaction | Implemented |
| Accidental HTTP calls | HTTP probing disabled by default | Implemented |
| Accidental model calls | Inference and cloud fallback disabled by default | Implemented |
| Cross-client data leakage | Tenant/client query enforcement | Future RBAC phase |
| Rate limiting | Route-level rate limits | Future hardening phase |

## Pre-promotion checklist

- [ ] `gitleaks detect --source . --log-opts HEAD` reports no secrets.
- [ ] `pip-audit --skip-editable` has no critical findings.
- [ ] License inventory confirms dependency compatibility.
- [ ] `scripts/validate_release.sh` passes.
- [ ] Docker Compose health check passes on a clean host.
- [ ] README and launch docs match current behavior.
