# Connector Setup

WAIT Local Agent keeps connector surfaces conservative by default.

## Safety Gates

| Gate | Default | Effect |
| --- | --- | --- |
| `WAIT_ALLOW_HTTP_PROBING` | `false` | Blocks all outbound PSA and documentation connector HTTP calls |
| `WAIT_ALLOW_WRITE_ACTIONS` | `false` | Blocks live HaloPSA and ConnectWise PSA write execution |
| Approval request | pending | Required before any HaloPSA or ConnectWise PSA draft can execute |

A fresh install can create PSA drafts but cannot mutate HaloPSA or ConnectWise PSA until the operator enables both the write gate and the approval flow.

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

## NinjaOne RMM

The public NinjaOne adapter implements the shared RMM contract for bounded
tenant-scoped device and alert inventory, script metadata, script preview, and
approval-aware script execution. It uses the documented OAuth bearer API and
device-script operation; see the [NinjaOne Public API](https://app.ninjaone.com/apidocs/)
and [public API operations](https://www.ninjaone.com/docs/application-programming-interface-api/public-api-operations/).

Required settings:

```text
WAIT_NINJAONE_BASE_URL=https://app.ninjarmm.com/api/v2
WAIT_NINJAONE_ACCESS_TOKEN=
WAIT_NINJAONE_ORGANIZATION_MAP_JSON={"acme":42}
WAIT_NINJAONE_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

`WAIT_NINJAONE_ORGANIZATION_MAP_JSON` is an explicit local map from the WAIT
tenant/client ID to a positive NinjaOne organization ID. Every request
requires a tenant ID, sends an organization filter where supported, and
defensively rejects returned rows outside the mapped organization. The
adapter does not accept credentials or provider organization IDs in smart
action payloads. Script execution remains behind `WAIT_ALLOW_WRITE_ACTIONS`
and the existing technician approval flow; previews do not make a write call.

The RMM smart actions are available through the `/smart-actions` API and
`smart-actions` CLI contract:

- `rmm-device-lookup`, `rmm-alert-lookup`, and `rmm-script-catalog` are bounded reads.
- `rmm-script-preview` validates a device and script without executing it.
- `rmm-script-execute` requires approval and both safety flags.
- `rmm-script-execution-lookup` returns only tenant-proven execution status.

Use a vault-backed token in shared or production-like installs:

```bash
wait-local-agent secrets set WAIT_NINJAONE_ACCESS_TOKEN '<oauth-access-token>'
```

The adapter has mocked transport coverage for scope filtering, approval
execution, response sanitization, blocked HTTP, malformed responses, timeouts,
and unauthorized/error responses. Live NinjaOne credentials are not required
for the test suite.

## Datto RMM

The public Datto RMM adapter implements the shared RMM contract for bounded,
tenant-scoped device and open-alert inventory plus component metadata. It uses
the documented OAuth bearer API and requires a local client-to-site map.
Component/device validation, approval-gated quick-job execution, and bounded
job-status lookup are available through the shared RMM contract. Quick-job
execution still requires a completed technician approval and
`WAIT_ALLOW_WRITE_ACTIONS=true`. See the [Datto RMM API documentation](https://rmm.datto.com/help/en/Content/2SETUP/APIv2.htm).

Required settings:

```text
WAIT_DATTORMM_BASE_URL=https://your-datto-api-host/api
WAIT_DATTORMM_ACCESS_TOKEN=
WAIT_DATTORMM_SITE_MAP_JSON={"acme":"site-uid"}
WAIT_DATTORMM_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

`WAIT_DATTORMM_SITE_MAP_JSON` maps each WAIT client ID to exactly one Datto
site UID. Datto API responses are bounded to the configured page size and
conflicting returned site identifiers are ignored. Credentials and provider
site IDs never come from smart-action payloads. The adapter has mocked
coverage for tenant mapping, scope filtering, bounded pagination parameters,
safe errors, blocked HTTP, malformed responses, and approval-gated quick-job
and status paths.

## N-able N-central

The N-central adapter is read-only and implements bounded tenant-scoped device,
active-issue, and scheduled-task metadata reads through the shared RMM contract.
It uses bearer authentication and an explicit WAIT client-to-organization-unit
map. N-central task execution and execution-status lookup are unavailable.

Required settings:

```text
WAIT_NCENTRAL_BASE_URL=https://your-ncentral-host
WAIT_NCENTRAL_ACCESS_TOKEN=
WAIT_NCENTRAL_ORG_UNIT_MAP_JSON={"acme":[100,101]}
WAIT_NCENTRAL_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

Every request requires a WAIT client ID whose organization-unit mapping is
configured locally. Responses are filtered to the mapped IDs and requests are
bounded to one GET page per endpoint. Credentials and provider IDs never come
from smart-action payloads. The adapter does not issue writes, even when
`WAIT_ALLOW_WRITE_ACTIONS=true`. See the [N-central devices API](https://developer.n-able.com/n-central/reference/listdevices),
[active issues API](https://developer.n-able.com/n-central/docs/active-issues-api),
and [task/job API overview](https://developer.n-able.com/n-central/docs/task-job-management-apis-overview).

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

## Microsoft 365 identity, group, license, mailbox, and Intune context

### Required settings

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
WAIT_ALLOW_WRITE_ACTIONS=true # required only for approved M365 lifecycle writes
```

The live connector accepts a delegated or application bearer token
obtained through the operator's Microsoft identity flow. Token acquisition is
outside the local agent and the token is never placed in URLs, query values, or
action payloads. Its read surface issues only bounded `GET /users` and
`GET /groups` requests plus selected-field `GET /subscribedSkus` and
`GET /users/{id}/mailFolders`, selected-field
`GET /users/{id}/mailFolders/{folder}/messages`, and
`GET /deviceManagement/managedDevices`
requests. User creation is a separate `POST /users` action and is disabled
unless the write flag is enabled and an admin approves the request. Store its
temporary password under a vault name beginning with `WAIT_M365_TEMP_`; the
Approved disable/offboarding is a separate admin-approved `PATCH /users/{id |
userPrincipalName}` action that sends only `{"accountEnabled": false}`. It
requires the application permission combination
`User.EnableDisableAccount.All` and `User.Read.All` (or the corresponding
delegated permission), and does not revoke sessions, remove licenses, mutate
mailbox data, or act on Intune devices. Approved group membership changes are
a separate action using immutable group and user IDs; they require
`GroupMember.ReadWrite.All` and support only explicit `add` or `remove`
operations through the approval queue.
Approved mailbox message moves are a separate admin-approved action using
explicit mailbox, source-folder, message, and destination-folder IDs. They
require `Mail.ReadWrite` and send only `destinationId` to Graph.
User lookup accepts a user ID or user principal name; group lookup accepts a
group ID, SMTP address, mail nickname, or exact display name. License context
is tenant-level subscribed-SKU metadata with aggregate counts; per-user license
details are not requested. Mailbox reads require an explicit user identity and
return only root-folder metadata and aggregate item counts; messages and hidden
folders are not requested. Group members and owners are not expanded. Managed-
device reads require an active
Intune tenant license and return selected inventory/compliance context only;
serial numbers, IMEI values, remote-assistance URLs, and action results are not
requested.

Microsoft documents `User.Read.All` for application user reads and
`User.ReadBasic.All` or `User.Read.All` for delegated work/school reads; grant
only the permission required by the chosen flow. Group context uses the
operator's approved group-read permission. Subscribed-SKU context uses
`LicenseAssignment.Read.All` for application or delegated access. Per-user
`licenseDetails` is intentionally not used because Microsoft does not support
application permissions for that endpoint. Intune managed-device reads use
`DeviceManagementManagedDevices.Read.All` for application or delegated access;
personal Microsoft accounts are not supported ([list users](https://learn.microsoft.com/en-us/graph/api/user-list?tabs=http&view=graph-rest-1.0), [list groups](https://learn.microsoft.com/en-us/graph/api/group-list?view=graph-rest-1.0), [list subscribed SKUs](https://learn.microsoft.com/en-us/graph/api/subscribedsku-list?view=graph-rest-1.0), [list mail folders](https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0), [list managed devices](https://learn.microsoft.com/en-us/graph/api/intune-devices-manageddevice-list?view=graph-rest-1.0), [permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)).

### Validate and read

```bash
wait-local-agent connectors validate m365
wait-local-agent connectors m365-health
wait-local-agent connectors m365-users
wait-local-agent connectors m365-users --identity user@example.com
wait-local-agent connectors m365-groups
wait-local-agent connectors m365-groups --identity helpdesk@example.com
wait-local-agent connectors m365-licenses
wait-local-agent connectors m365-mail-folders --identity user@example.com
wait-local-agent connectors m365-mail-messages user@example.com inbox-id
wait-local-agent connectors m365-managed-devices
wait-local-agent connectors draft-m365-managed-device-sync device-1
wait-local-agent connectors draft-m365-managed-device-reboot device-1
wait-local-agent connectors draft-m365-mail-message-move user-1 inbox-id message-id archive-id
wait-local-agent connectors draft-m365-mail-message-read-state user-1 inbox-id message-id --unread
wait-local-agent connectors draft-m365-mail-message-delete user-1 inbox-id message-id
```

The API mirrors these commands under `/connectors/m365/health` and
`/connectors/m365/users`, `/connectors/m365/groups`,
`/connectors/m365/licenses`, `/connectors/m365/mail-folders`,
`/connectors/m365/mail-messages`, and `/connectors/m365/managed-devices`.
Message moves are exposed through
`POST /connectors/m365/mail-messages/move-drafts` with
`user_identity`, `source_folder_id`, `message_id`, and
`destination_folder_id`.
Read-state changes are exposed through
`POST /connectors/m365/mail-messages/read-state-drafts` with
`user_identity`, `source_folder_id`, `message_id`, and the boolean `is_read`.
Both actions require administrator approval before execution.
Message deletion is exposed through
`POST /connectors/m365/mail-messages/delete-drafts` with
`user_identity`, `source_folder_id`, and `message_id`; it is also
administrator-approved and does not expose permanent deletion.
Managed-device sync is exposed through
`POST /connectors/m365/managed-devices/sync-drafts` with `device_id`; it is
administrator-approved, sends no request body, and does not expose wipe or
delete.
Managed-device reboot is exposed through
`POST /connectors/m365/managed-devices/reboot-drafts` with `device_id`; it is
administrator-approved, sends no request body, and does not expose wipe or
delete. It requires the privileged managed-device Graph permission.
Approved user creation is exposed through `POST /connectors/m365/users/drafts`
and `POST /connectors/m365/approval-requests/{id}/execute`, or the CLI commands
`connectors draft-m365-user` and `connectors execute-m365-user`. Approved
disable/offboarding is exposed through
`POST /connectors/m365/users/disable-drafts` and the same execution endpoint,
or `connectors draft-m365-user-disable` and `connectors execute-m365`.
Approved group membership changes are exposed through
`POST /connectors/m365/groups/membership-drafts` with `group_id`, `user_id`,
and `operation` (`add` or `remove`), or the CLI command
`connectors draft-m365-group-membership GROUP_ID USER_ID --operation add|remove`.
Approved direct user license changes are exposed through
`POST /connectors/m365/users/license-drafts` with `user_id`, `sku_ids`, and
`operation` (`add` or `remove`), or the CLI command
`connectors draft-m365-license-change USER_ID --sku-id SKU_ID --operation add|remove`.
Approved session revocation is exposed through
`POST /connectors/m365/users/session-revocation-drafts` or the CLI command
`connectors draft-m365-session-revocation USER_ID`.

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

The adapter uses the ConnectWise PSA REST ticket and company surfaces. It
normalizes only the fields needed by the local agent. Ticket writes use a
bounded JSON-patch map and never accept arbitrary endpoints, fields, company
identifiers, or credentials in request payloads.

### Validate and read

```bash
wait-local-agent connectors validate connectwise
wait-local-agent connectors connectwise-health
wait-local-agent connectors connectwise-tickets
wait-local-agent connectors connectwise-ticket <ticket-id>
wait-local-agent connectors connectwise-companies
wait-local-agent connectors connectwise-write-health
```

The API mirrors these commands under `/connectors/connectwise/health`,
`/connectors/connectwise/tickets`, and `/connectors/connectwise/companies`.
All routes remain viewer-authenticated and rate-limited.

### Approved ticket updates

```bash
wait-local-agent connectors draft-connectwise CW-1002 update_status --field status_id=42
wait-local-agent approvals show <request-id>
wait-local-agent approvals update <request-id> approved 'approved by technician'
wait-local-agent connectors execute-connectwise <request-id>
```

Live updates require both `WAIT_ALLOW_HTTP_PROBING=true` and
`WAIT_ALLOW_WRITE_ACTIONS=true`. Supported action types are `update_status`,
`assign_technician` (`owner_id` or `team_id`), and `update_ticket_fields`
(`summary`, `description`, `status_id`, `priority_id`, `board_id`, `owner_id`,
or `team_id`).

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
