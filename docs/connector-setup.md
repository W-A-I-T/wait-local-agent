# Connector Setup

WAIT Local Agent keeps connector surfaces conservative by default.

## Safety Gates

| Gate | Default | Effect |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Blocks all outbound HaloPSA, Hudu, NinjaOne, and Autotask HTTP calls |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Blocks live HaloPSA write execution |
| Approval request | pending | Required before any HaloPSA draft can execute |

A fresh install can create HaloPSA drafts but cannot mutate HaloPSA until the operator enables both the write gate and the approval flow.

## API Authentication

For shared environments, disable demo mode and use bearer tokens:

```text
WAIT_DEMO_MODE=false
WAIT_ADMIN_TOKEN=
WAIT_TECH_TOKEN=
WAIT_VIEWER_TOKEN=
```

You can keep `WAIT_API_TOKEN` for the legacy admin-equivalent token if needed.

Example:

```bash
export WAIT_ADMIN_TOKEN='<admin-token>'
curl -H "Authorization: Bearer $WAIT_ADMIN_TOKEN" http://127.0.0.1:8788/health
```

## Secrets Backend

Default development path:

```text
WAIT_SECRETS_BACKEND=env
```

Vault-backed path:

```bash
WAIT_SECRETS_BACKEND=fernet
WAIT_VAULT_PATH=.wait-local-agent/vault
wait-local-agent secrets init
wait-local-agent secrets set WAIT_HALOPSA_CLIENT_SECRET '<secret>'
wait-local-agent secrets set WAIT_HUDU_API_KEY '<secret>'
wait-local-agent secrets list
```

`wait-local-agent secrets list` prints names only. Treat `wait-local-agent secrets get` output as sensitive.

## HaloPSA

### Required settings

```text
WAIT_HALOPSA_BASE_URL=
WAIT_HALOPSA_CLIENT_ID=
WAIT_HALOPSA_CLIENT_SECRET=
WAIT_HALOPSA_TENANT=
WAIT_HALOPSA_TOKEN_URL=
WAIT_ALLOW_HTTP_PROBING=true
```

Optional endpoint overrides:

```text
WAIT_HALOPSA_TICKET_WRITE_ENDPOINT=Ticket
WAIT_HALOPSA_ACTION_WRITE_ENDPOINT=Actions
```

### Validate credentials first

```bash
wait-local-agent connectors validate halopsa
```

Validation behavior:

- exits `0` and prints `PASS ...` when credentials and probing work
- exits non-zero and prints `FAIL ...` when config is incomplete or the health call fails

### Read-only checks

```bash
wait-local-agent connectors halopsa-health
wait-local-agent connectors halopsa-tickets
wait-local-agent connectors halopsa-ticket <ticket-id>
wait-local-agent connectors halopsa-notes <ticket-id>
wait-local-agent connectors halopsa-clients
wait-local-agent connectors halopsa-assets <client-id>
wait-local-agent connectors halopsa-categories
```

### Write readiness

Check write prerequisites without executing a write:

```bash
wait-local-agent connectors halopsa-write-health
```

Live HaloPSA writes require all of the following:

1. `WAIT_ALLOW_HTTP_PROBING=true`
2. `WAIT_ALLOW_WRITE_ACTIONS=true`
3. configured credentials
4. a pending draft
5. explicit approval

### Draft and approval flow

```bash
wait-local-agent connectors draft-halopsa HALO-1002 add_note \
  --field note='Internal note ready for review'
wait-local-agent approvals show 1
wait-local-agent approvals edit-field 1 note='Reviewed by technician'
wait-local-agent approvals update 1 approved 'approved by technician'
wait-local-agent connectors execute-halopsa 1
```

The execution record stores sanitized metadata only: action type, ticket id, endpoint, status, HTTP status, remote id when present, and a concise result message.

## Hudu

### Required settings

```text
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
WAIT_HUDU_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

### Validate credentials first

```bash
wait-local-agent connectors validate hudu
```

### Read-only checks

```bash
wait-local-agent connectors hudu-health
wait-local-agent connectors hudu-companies
wait-local-agent connectors hudu-articles
wait-local-agent connectors hudu-article <article-id>
wait-local-agent connectors hudu-folders
```

Hudu is read-only in the public repo. There is no Hudu write surface to enable.

## NinjaOne RMM

The public NinjaOne adapter is read-only. It lists devices, active alerts, and
automation script metadata, and can create a redacted script execution preview.
It never calls NinjaOne script execution or management endpoints.

### Required settings

```text
WAIT_NINJAONE_BASE_URL=https://app.ninjarmm.com
WAIT_NINJAONE_CLIENT_ID=
WAIT_NINJAONE_CLIENT_SECRET=
WAIT_NINJAONE_SCOPE=monitoring
WAIT_NINJAONE_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

Use a NinjaOne OAuth application with monitoring scope. Keep the client secret
in the Fernet vault for appliance deployments:

```bash
wait-local-agent secrets set WAIT_NINJAONE_CLIENT_SECRET '<secret>'
wait-local-agent connectors validate ninjaone
```

### Read and preview commands

```bash
wait-local-agent connectors ninjaone-health
wait-local-agent connectors ninjaone-devices
wait-local-agent connectors ninjaone-device <device-id>
wait-local-agent connectors ninjaone-alerts
wait-local-agent connectors ninjaone-scripts
wait-local-agent connectors ninjaone-script-preview <device-id> <script-id>
```

The API equivalents are under `/connectors/ninjaone`. The script preview
returns variable names only; variable values are never echoed or persisted.

## Autotask PSA

The public Autotask adapter is read-only. It lists tickets and companies and
does not call mutation endpoints. Configure the API-only user credentials and
integration code in the local vault when possible:

```bash
wait-local-agent secrets init
wait-local-agent secrets set WAIT_AUTOTASK_BASE_URL
wait-local-agent secrets set WAIT_AUTOTASK_USERNAME
wait-local-agent secrets set WAIT_AUTOTASK_SECRET
wait-local-agent secrets set WAIT_AUTOTASK_INTEGRATION_CODE
WAIT_ALLOW_HTTP_PROBING=true wait-local-agent connectors validate autotask
```
