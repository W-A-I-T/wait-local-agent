# Connector Setup

WAIT Local Agent keeps connector surfaces conservative by default.

## Safety Gates

| Gate | Default | Effect |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Blocks all outbound HaloPSA, Hudu, IT Glue, NinjaOne, Autotask, ConnectWise, Syncro, and ServiceNow HTTP calls |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Blocks live HaloPSA writes and NinjaOne script execution |
| Approval request | pending | Required before any HaloPSA or NinjaOne action can execute |

A fresh install can create approval requests but cannot mutate HaloPSA or run a NinjaOne script until the operator enables both the write gate and the approval flow.

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

## IT Glue

The public IT Glue adapter is read-only. It lists organizations, organization
documents, and document folders, and retrieves one document at a time. It does
not call IT Glue create, update, or delete endpoints.

### Required settings

```text
WAIT_ITGLUE_BASE_URL=https://api.itglue.com
WAIT_ITGLUE_API_KEY=
WAIT_ITGLUE_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

IT Glue API keys are sent only in the `x-api-key` request header, matching the
[IT Glue API authentication documentation](https://api.itglue.com/developer/).
Store the key in the Fernet vault for appliance deployments:

```bash
wait-local-agent secrets set WAIT_ITGLUE_API_KEY '<secret>'
wait-local-agent connectors validate itglue
```

Read-only commands use organization-scoped document and folder paths:

```bash
wait-local-agent connectors itglue-health
wait-local-agent connectors itglue-organizations
wait-local-agent connectors itglue-documents <organization-id>
wait-local-agent connectors itglue-document <document-id>
wait-local-agent connectors itglue-folders <organization-id>
```

## NinjaOne RMM

The public NinjaOne adapter is read-first. It lists devices, active alerts, and
automation script metadata, creates redacted execution previews, and supports
one approval-gated script execution action. It does not expose general
NinjaOne management endpoints.

### Required settings

```text
WAIT_NINJAONE_BASE_URL=https://app.ninjarmm.com
WAIT_NINJAONE_CLIENT_ID=
WAIT_NINJAONE_CLIENT_SECRET=
WAIT_NINJAONE_SCOPE=monitoring
WAIT_NINJAONE_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
WAIT_ALLOW_WRITE_ACTIONS=false
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
wait-local-agent connectors ninjaone-script-request <device-id> <script-id> '{}'
wait-local-agent connectors ninjaone-script-execute <approval-id>
```

The API equivalents are under `/connectors/ninjaone`. The request endpoint only
creates a pending approval. Execution additionally requires both safety flags
and rejects secret-like variable names; execution results persist only bounded
metadata, never script parameters.

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

## ConnectWise PSA

The public ConnectWise adapter is read-only and requires explicit HTTP
probing. Configure the API base URL, company identifier, public/private API
keys, and application client ID. The adapter only reads service tickets and
companies; it does not call ConnectWise mutation endpoints.

```bash
wait-local-agent secrets set WAIT_CONNECTWISE_BASE_URL
wait-local-agent secrets set WAIT_CONNECTWISE_COMPANY_ID
wait-local-agent secrets set WAIT_CONNECTWISE_PUBLIC_KEY
wait-local-agent secrets set WAIT_CONNECTWISE_PRIVATE_KEY
wait-local-agent secrets set WAIT_CONNECTWISE_CLIENT_ID
WAIT_ALLOW_HTTP_PROBING=true wait-local-agent connectors validate connectwise
```

## SyncroMSP

The public Syncro adapter is read-only and requires explicit HTTP probing. Set
the Syncro subdomain API base URL and API key. Syncro documents the API key as a
query parameter; the local adapter never includes it in connector result,
audit, or error messages.

```bash
wait-local-agent secrets set WAIT_SYNCRO_BASE_URL
wait-local-agent secrets set WAIT_SYNCRO_API_KEY
wait-local-agent secrets set WAIT_SYNCRO_PAGE_SIZE
WAIT_ALLOW_HTTP_PROBING=true wait-local-agent connectors validate syncro
```

Use the vendor's current API documentation when selecting the account and
subdomain endpoint: <https://api-docs.syncromsp.com/>.

## ServiceNow

The public ServiceNow adapter is read-only and requires explicit HTTP probing.
Configure an instance URL and a least-privileged account that can read the
`incident` and `core_company` tables. The adapter requests only a narrow field
set and never calls ServiceNow mutation methods.

```bash
wait-local-agent secrets set WAIT_SERVICENOW_BASE_URL
wait-local-agent secrets set WAIT_SERVICENOW_USERNAME
wait-local-agent secrets set WAIT_SERVICENOW_PASSWORD
wait-local-agent secrets set WAIT_SERVICENOW_PAGE_SIZE
WAIT_ALLOW_HTTP_PROBING=true wait-local-agent connectors validate servicenow
```

Use the official Table API documentation when validating instance ACLs and
table permissions: <https://developer.servicenow.com/dev.do#!/reference>.
