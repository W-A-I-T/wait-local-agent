# WAIT Ecosystem Integration

> How WAIT Local Agent connects to WAIT Launch Passport, Investor Diligence Passport, and WAit-Adaptations.

All ecosystem connections are **optional, user-triggered, and privacy-preserving**. WAIT Local Agent operates fully offline by default. No data leaves the operator's hardware unless the operator explicitly configures and triggers an upload.

---

## Ecosystem Overview

```
WAIT Local Agent (Founder Pack)
    ↓ project scan — local only, no execution, no source code
Evidence Vault (SQLite + Fernet, local)
    ↓ user-triggered upload with diff preview (explicit confirmation)
    POST /api/projects/:id/artifacts/collector-bundle
    Authorization: Bearer {lp_upload_token}
WAIT Launch Passport (cloud, user's account)
    ↓ static/runtime scan on uploaded bundle + any other evidence
    LaunchPassportReport (readiness score, findings, blockers, unknowns)
    ↓ user purchases IDP Technical Add-on ($999)
    POST /api/projects/:id/investor-pack
Investor Diligence Passport (cloud, user's account)
    ↓ imports LP investor pack markdown as evidence
    Investor Diligence Report + PDF
```

WAit-Adaptations (AER) is not called directly by WAIT Local Agent. Escalations flow through LP:
```
LP → POST /api/projects/:id/wait-adaptation/escalation → AER
```

---

## Data Contract: CollectorBundle Format

WAIT Local Agent Founder Pack produces a bundle compatible with LP's `CollectorBundle` type (defined in `packages/collector/src/collect.ts` in `wait-launch-passport`).

```json
{
  "metadata": {
    "collectorVersion": "wait-local-agent/1.0",
    "collectedAt": "2026-06-10T00:00:00Z",
    "root": "[redacted — absolute path stripped]",
    "sourceCode": false,
    "agentId": "UUID — generated on first appliance init",
    "bundleHash": "sha256hex of bundle JSON before signing",
    "signature": "hmac-sha256hex with user vault key"
  },
  "files": [
    {"path": "src/", "type": "directory"},
    {"path": "src/main.py", "size": 1234}
  ],
  "dependencies": {
    "npmAudit": null,
    "pipAudit": {"vulnerabilities": [...]}
  },
  "findings": {
    "semgrep": {"results": [...], "errors": []},
    "gitleaks": {"findings": [...]},
    "npmAudit": null,
    "pipAudit": {"vulnerabilities": [...]}
  },
  "routes": ["/api/v1/users", "/api/v1/projects"],
  "environment": {
    "keys": {
      "backend": ["OPENAI_API_KEY", "DATABASE_URL", "STRIPE_SECRET_KEY"]
    }
  },
  "hashes": [
    {"path": "src/main.py", "sha256": "abc123..."}
  ],
  "testing": {
    "hasTests": true,
    "ciWorkflows": 2,
    "frameworks": ["pytest"],
    "testFileCount": 12
  }
}
```

### Privacy Rules — Enforced Before Upload

| Rule | What it means | How enforced |
|------|--------------|-------------|
| `sourceCode: false` always | No file contents ever uploaded | Hardcoded in scanner; validated by `BundleValidator` before upload |
| Relative paths only | No local path leakage | Absolute path prefix stripped in scanner |
| Environment key names only | No environment variable values | Scanner reads `.env.example` for key names; never reads `.env` or secret files |
| gitleaks: type + path + severity only | No secret values | gitleaks output parsed; value field never included |
| Bundle hash + HMAC | Integrity verification | LP verifies hash on receipt; tampering detectable |
| User explicit trigger | No background sync ever | Upload requires CLI command or dashboard button; no automation |

---

## Bundle Signing Model

```python
# Local Agent vault signing
bundle_bytes = json.dumps(bundle, sort_keys=True).encode("utf-8")
bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()

# vault_key loaded from Fernet-encrypted vault.key.enc (never transmitted)
# vault_key[:32] used as HMAC key
signature = hmac.new(vault_key[:32], bundle_hash.encode(), "sha256").hexdigest()

# Both hash and signature included in bundle.metadata
# LP stores bundle_hash; can verify integrity on download
# Vault key is user-generated, user-held; WAIT cannot read it
```

The vault key is generated locally on `wait founder vault init`. It is stored in `data/vault.key.enc` (Fernet-encrypted with the operator's master secret). If the vault key is lost, the local bundles are unrecoverable — this is intentional; the user owns their evidence.

---

## API Boundaries

| Caller | Endpoint | Auth | Direction | Notes |
|--------|---------|------|-----------|-------|
| Local Agent → LP | `GET /api/projects/:id/collector-upload-tokens` | LP API key | Pull | Get temporary upload token |
| Local Agent → LP | `POST /api/projects/:id/artifacts/collector-bundle` | Bearer upload_token | Push | Upload signed bundle |
| Local Agent → LP | `GET /api/projects/:id/scans` | LP API key | Read | Check scan status after upload |
| LP → AER | `POST /api/projects/:id/wait-adaptation/escalation` | Internal service token | Push | LP manages this; Local Agent does not call AER directly |
| IDP → LP | `POST /api/projects/:id/investor-pack` | LP_API_SERVICE_TOKEN | Push | IDP manages this; Local Agent does not call IDP directly |

---

## Authorization and Ownership

- Each appliance has a `WAIT_AGENT_ID` (UUID generated on first `wait doctor` run)
- User creates an LP project manually and obtains `projectId` + upload token from LP dashboard
- User stores `WAIT_LP_PROJECT_ID` and `WAIT_LP_API_KEY` in local vault (never in `.env`)
- Upload token is short-lived; `lp_client.py` refreshes automatically before each upload
- The appliance stores last token + expiry in `founder_config` SQLite table
- No LP account is created automatically; user connects explicitly

---

## Offline Mode (Default)

When no LP config is present (`WAIT_LP_PROJECT_ID` not set):
- All Local Agent operations work normally (scan, vault, preflight, handoff, ask)
- Upload features are hidden in the UI
- `wait doctor` reports: "LP: not configured (offline mode)"
- `wait founder upload` exits with a clear message: "Configure WAIT_LP_PROJECT_ID and WAIT_LP_API_KEY to upload"
- No errors, no degraded functionality

This is the default experience for MSP users (who never need LP) and for founders who are not yet ready to purchase an LP scan.

---

## Cloud-Connected Mode (Opt-in)

When the user configures LP credentials:
1. `wait doctor` reports: "LP: connected — project: <name>"
2. `wait founder upload --artifact-id <id>` shows a diff preview before upload
3. User confirms → bundle uploaded → LP queues scan
4. `wait founder status` shows scan progress
5. On completion: `wait founder scan-report` fetches the LP report summary
6. LP dashboard link shown for full report

---

## Artifact Retention Rules

| Location | Retention | Control |
|---------|-----------|---------|
| Local vault (SQLite + encrypted files) | Default 90 days, configurable via `WAIT_VAULT_RETENTION_DAYS` | Operator-controlled |
| LP cloud artifacts | LP's own retention policy | User-controlled in LP dashboard |
| Local bundles (exported JSON files) | Operator-managed; not auto-deleted | User is responsible |

The local agent never deletes LP-stored artifacts. LP manages its own retention.

---

## IDP Integration (Founder Pack)

The Investor Diligence Passport connection flows through LP:

1. Founder has an LP project with a completed scan
2. Founder purchases the IDP Technical Add-on SKU ($999) on IDP
3. IDP calls `POST /api/projects/:id/investor-pack` on LP with `Authorization: Bearer {LP_API_SERVICE_TOKEN}`
4. LP returns `investor_pack_markdown` — a structured technical evidence document
5. IDP imports this as a document in its evidence pipeline

WAIT Local Agent's role: it improves the quality of the LP scan (by providing a rich, pre-validated CollectorBundle) which in turn improves the IDP Technical Add-on output. There is no direct Local Agent → IDP API call.

---

## AER Integration (Startup/Enterprise)

WAit-Adaptations (Adaptive Execution Runtime) is accessed exclusively through LP's escalation endpoint. WAIT Local Agent does not call AER directly.

Future enterprise scenario (Phase 7+): If both WAIT Local Agent and AER are deployed in the same private network (enterprise air-gap), AER could consume the Local Agent's evidence bundle directly via a private API contract. This is out of scope until Phase 7.
