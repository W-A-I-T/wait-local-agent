# Connector Setup

WAIT Local Agent keeps connector surfaces conservative by default.

## Safety Gates

| Gate | Default | Effect |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Blocks all outbound PSA and documentation connector HTTP calls |
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
wait-local-agent secrets set WAIT_CONNECTWISE_PRIVATE_KEY '<secret>'
wait-local-agent secrets set WAIT_SYNCRO_API_TOKEN '<secret>'
wait-local-agent secrets set WAIT_SERVICENOW_PASSWORD '<secret>'
wait-local-agent secrets set WAIT_AUTOTASK_SECRET '<secret>'
wait-local-agent secrets set WAIT_AUTOTASK_INTEGRATION_CODE '<tracking-identifier>'
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

### Required settings

```text
WAIT_ITGLUE_BASE_URL=https://api.itglue.com
WAIT_ITGLUE_API_KEY=
WAIT_ITGLUE_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

The adapter uses the documented IT Glue JSON:API organization relationship
routes for documents and folders. API keys are sent only in the request header;
no write operation is exposed ([IT Glue API documentation](https://api.itglue.com/developer/)).

### Validate and read

```bash
wait-local-agent connectors validate itglue
wait-local-agent connectors itglue-health
wait-local-agent connectors itglue-organizations
wait-local-agent connectors itglue-documents <organization-id>
wait-local-agent connectors itglue-document <document-id>
wait-local-agent connectors itglue-folders <organization-id>
```

The API mirrors these commands under `/connectors/itglue/health`,
`/connectors/itglue/organizations`, and the organization-scoped document and
folder routes.

## Confluence Cloud

### Required settings

```text
WAIT_CONFLUENCE_BASE_URL=https://your-site.atlassian.net
WAIT_CONFLUENCE_EMAIL=
WAIT_CONFLUENCE_API_TOKEN=
WAIT_CONFLUENCE_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

The read-only adapter uses Confluence Cloud REST API v2 page listing and page
detail. Direct API access uses basic authentication with the account email and
API token; the token is never placed in a URL or request payload. Listing is
bounded with `limit` and exposes the documented next cursor for continuation.
No mutation endpoint is exposed ([Confluence REST API v2](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/)).

### Validate and read

```bash
wait-local-agent connectors validate confluence
wait-local-agent connectors confluence-health
wait-local-agent connectors confluence-pages
wait-local-agent connectors confluence-page <page-id>
```

The API mirrors these commands under `/connectors/confluence/health`,
`/connectors/confluence/pages`, and `/connectors/confluence/pages/{page-id}`.

## SharePoint

### Required settings

```text
WAIT_SHAREPOINT_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_SHAREPOINT_ACCESS_TOKEN=
WAIT_SHAREPOINT_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

The adapter uses Microsoft Graph site and drive-item metadata endpoints. It
accepts a delegated or application bearer token obtained by the operator's
chosen Microsoft identity flow; token acquisition is intentionally outside the
local agent and the token is never placed in URLs or request payloads. The
adapter returns bounded metadata only: it does not download file contents or
expose mutation endpoints. Microsoft documents `Sites.Read.All` as the least
privileged application permission for site reads and `Files.Read.All` for drive
children reads ([Get a SharePoint site](https://learn.microsoft.com/en-us/graph/api/site-get?view=graph-rest-1.0), [list drive children](https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?tabs=http&view=graph-rest-1.0)).

### Validate and read

```bash
wait-local-agent connectors validate sharepoint
wait-local-agent connectors sharepoint-health
wait-local-agent connectors sharepoint-sites
wait-local-agent connectors sharepoint-site <site-id>
wait-local-agent connectors sharepoint-documents <site-id>
wait-local-agent connectors sharepoint-document <site-id> <item-id>
```

The API mirrors these commands under `/connectors/sharepoint/health`,
`/connectors/sharepoint/sites`, and the site-scoped document routes.

## ConnectWise PSA

### Required settings

```text
WAIT_CONNECTWISE_BASE_URL=
WAIT_CONNECTWISE_COMPANY=
WAIT_CONNECTWISE_PUBLIC_KEY=
WAIT_CONNECTWISE_PRIVATE_KEY=
WAIT_CONNECTWISE_CLIENT_ID=
WAIT_CONNECTWISE_API_VERSION=2022.1
WAIT_CONNECTWISE_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

The adapter uses the documented ConnectWise PSA REST read endpoints for tickets
and companies. It normalizes only the fields needed by the local agent and has
no mutation or credential-in-request-payload path.

### Validate and read

```bash
wait-local-agent connectors validate connectwise
wait-local-agent connectors connectwise-health
wait-local-agent connectors connectwise-tickets
wait-local-agent connectors connectwise-ticket <ticket-id>
wait-local-agent connectors connectwise-companies
```

The API mirrors these commands under `/connectors/connectwise/health`,
`/connectors/connectwise/tickets`, and `/connectors/connectwise/companies`.
All routes remain viewer-authenticated and rate-limited.

## Syncro

### Required settings

```text
WAIT_SYNCRO_BASE_URL=
WAIT_SYNCRO_API_TOKEN=
WAIT_ALLOW_HTTP_PROBING=true
```

The Syncro adapter is read-only and uses the documented ticket/customer GET
surfaces with bearer authentication ([official Syncro API docs](https://api-docs.syncromsp.com/)).
It keeps credentials in settings/vault, does not place them in URLs or
payloads, and has no write path.

### Validate and read

```bash
wait-local-agent connectors validate syncro
wait-local-agent connectors syncro-health
wait-local-agent connectors syncro-tickets
wait-local-agent connectors syncro-ticket <ticket-id>
wait-local-agent connectors syncro-customers
wait-local-agent connectors syncro-customer <customer-id>
```

The API mirrors these commands under `/connectors/syncro/health`,
`/connectors/syncro/tickets`, and `/connectors/syncro/customers`.

## ServiceNow

### Required settings

```text
WAIT_SERVICENOW_BASE_URL=
WAIT_SERVICENOW_USERNAME=
WAIT_SERVICENOW_PASSWORD=
WAIT_SERVICENOW_API_VERSION=v1
WAIT_SERVICENOW_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

The read-only adapter uses ServiceNow's Table API for incidents and companies,
with explicit field selection, bounded pagination, and basic authentication
from settings or the local vault ([ServiceNow Table API](https://www.servicenow.com/docs/r/xanadu/api-reference/rest-apis/c_TableAPI.html)).
No mutation endpoint is exposed.

### Validate and read

```bash
wait-local-agent connectors validate servicenow
wait-local-agent connectors servicenow-health
wait-local-agent connectors servicenow-incidents
wait-local-agent connectors servicenow-incident <sys-id>
wait-local-agent connectors servicenow-companies
wait-local-agent connectors servicenow-company <sys-id>
```

The API mirrors these commands under `/connectors/servicenow/health`,
`/connectors/servicenow/incidents`, and `/connectors/servicenow/companies`.

## Autotask PSA

### Required settings

```text
WAIT_AUTOTASK_BASE_URL=
WAIT_AUTOTASK_USERNAME=
WAIT_AUTOTASK_SECRET=
WAIT_AUTOTASK_INTEGRATION_CODE=
WAIT_AUTOTASK_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

The read-only adapter uses Autotask REST GET operations for ticket and company
inventory. It sends the username, secret, and integration code only in
request headers, bounds list pagination, validates resource identifiers, and
distinguishes blocked, missing, unauthorized, and failed states ([Autotask REST API](https://psa.datto.com/help/DeveloperHelp/Content/APIs/REST/REST_API_Home.htm)).
No mutation endpoint is exposed.

### Validate and read

```bash
wait-local-agent connectors validate autotask
wait-local-agent connectors autotask-health
wait-local-agent connectors autotask-tickets
wait-local-agent connectors autotask-ticket <ticket-id>
wait-local-agent connectors autotask-companies
wait-local-agent connectors autotask-company <company-id>
```

The API mirrors these commands under `/connectors/autotask/health`,
`/connectors/autotask/tickets`, `/connectors/autotask/companies`, and the
company detail route `/connectors/autotask/companies/{company_id}`.
