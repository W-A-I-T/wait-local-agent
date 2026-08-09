# Security Model

WAIT Local Agent is designed to be safe by default. Potentially dangerous capabilities require explicit operator opt-in and are disabled in fresh installs.

## Safe-by-default flags

| Flag | Default | Required for |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Outbound HTTP calls to PSA, RMM, or knowledge systems |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Live connector mutations |
| `WAIT_ALLOW_LLM_INFERENCE` | `false` | Local model calls |
| `WAIT_ALLOW_CLOUD_FALLBACK` | `false` | Cloud model calls after local timeout |
| `WAIT_REMOTE_MODEL_*` | empty | No remote provider is configured; a complete provider, base URL, model, and secret plus both model opt-ins are required |
| `WAIT_ALLOW_OCR` | `false` | OCR processing of scanned documents |
| `WAIT_END_USER_SUPPORT_ENABLED` | `false` | Optional scoped end-user ticket routes |

HaloPSA live writes require all of the following: `WAIT_ALLOW_HTTP_PROBING=true`, `WAIT_ALLOW_WRITE_ACTIONS=true`, complete connector credentials, and an approved `ApprovalRequest` record.

Remote model requests are never part of local-only operation. When explicitly
enabled, the provider adapter sends only bounded, redacted ticket and local
knowledge context; it does not send tenant IDs, local paths, credentials, or
hidden reasoning. Provider/model labels are retained as safe operational
metadata, while API keys remain in the configured env/vault secret boundary.

NinjaOne RMM calls use the same outbound HTTP gate. A tenant/client request is
accepted only when its ID resolves through the operator-controlled
`WAIT_NINJAONE_ORGANIZATION_MAP_JSON`; provider IDs and credentials are not
request-supplied authorization inputs. Inventory and execution lookup apply
returned-row scope checks. Script execution additionally requires
`WAIT_ALLOW_WRITE_ACTIONS=true` and a completed technician approval.

Datto RMM calls use the same outbound HTTP gate. Each request requires a
client ID that resolves through operator-controlled
`WAIT_DATTORMM_SITE_MAP_JSON`; provider site IDs and credentials are never
request-supplied authorization inputs. Device and alert responses are checked
against the mapped site when the provider returns a site identifier. The
Quick-job execution additionally requires `WAIT_ALLOW_WRITE_ACTIONS=true` and
is only reachable from the approved RMM script smart action. The adapter
validates the component and device against the mapped tenant before issuing
the documented quick-job request; job status lookup is bounded to the returned
job identifier and does not expose component output.

N-able N-central calls use the same outbound HTTP gate and require a client ID
that resolves through `WAIT_NCENTRAL_ORG_UNIT_MAP_JSON`. The adapter sends only
GET requests, limits each endpoint to one configured page, and rejects returned
devices, issues, or tasks outside the mapped organization units. Credentials
and provider IDs are never request-supplied, and the N-central adapter exposes
no write or execution-status operation.

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
policy. Automatic retries run locally in bounded batches, use a 60-second
initial delay with exponential backoff capped at one hour, and expose only the
redacted `next_retry_at` timestamp.

Workflow-template revision comparisons require viewer access and resolve both
revisions through the same tenant-scoped gallery entry. Comparison responses
contain only redacted stored definition fields; they do not restore, execute, or
change a template.

Workflow-run comparisons require viewer access and resolve both runs through the
same authenticated tenant scope. Comparison responses redact run messages and
contain only operational fields; they do not expose execution payloads or permit
reruns, approval changes, or other mutations.

Workflow-template exports are viewer-readable but omit local gallery ids,
timestamps, and tenant identity. They apply the existing redaction policy to
editable text. Imports require technician access, validate the artifact format
and source template against the reviewed built-in catalog, apply the
authenticated tenant scope, and create the copy disabled so an operator must
review it before enabling execution. Imported artifacts cannot supply arbitrary
tools, source metadata, or authorization scope.

Execution metadata is stored through the same redacting JSON path as execution
steps. Smart-action records may include only configured provider/model labels;
credentials, prompts, and hidden reasoning are not added to execution metadata.

Hudu is read-only in the public repo.

The Syncro, ServiceNow, and Autotask agent lookup tools are read-only and
require an existing local ticket in the caller's tenant scope. Each lookup
uses that ticket identifier as the provider request identifier and rejects a
returned record whose identifier does not match; connector credentials are
never accepted in tool payloads.

The IT Glue documentation tool is also read-only. It requires an explicit
organization identifier matching the caller's tenant scope, bounds the
organization document query and local result filter, and rejects returned
documents that identify a different organization.

Confluence and SharePoint documentation tools are read-only metadata surfaces.
They require a space/site identifier matching the caller's tenant scope, bound
the provider page or drive-item query, and do not return page bodies or file
contents.

The `m365-live-context` tool accepts only a fixed read-resource enum and bounded
identity/page-size inputs. It never accepts a Graph token or tenant identifier;
the existing configured-provider gates enforce outbound access. Message reads
select metadata only and never return bodies, previews, or attachments, while
all M365 mutations remain on the separate approval-draft and execution paths.
Message moves are separately approval-gated, use only explicit
mailbox/folder/message IDs, send only a destination folder ID to Graph, and do
not expose send or message-content operations. Read-state changes are
separately approval-gated, use the same explicit IDs, and send only the
boolean `isRead` field to Graph.
Message deletion is separately approval-gated, uses only explicit
mailbox/folder/message IDs, sends no request body, and does not expose
permanent deletion.
Managed-device sync is separately approval-gated, uses only a strict device ID,
sends no request body, and does not expose wipe or delete operations.
Managed-device reboot follows the same approval, strict-ID, write-flag, and
bodyless-request controls; wipe and delete operations remain unavailable.

ConnectWise PSA ticket writes are restricted to three named actions and a
closed field-to-JSON-patch map. They require HTTP probing, the global write
flag, a persisted approval request, and explicit approval. The adapter rejects
arbitrary endpoint paths, fields, company identifiers, and credential values;
execution results retain only endpoint/status metadata.

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
