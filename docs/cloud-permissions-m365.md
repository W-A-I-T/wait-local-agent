# Microsoft 365 cloud inventory permissions

The Microsoft 365 adapter calls bounded Microsoft Graph read endpoints and one
approval-gated user-creation endpoint. For an
application credential, grant administrator-consented application
permissions:

| Inventory | Required permission |
| --- | --- |
| Tenant preflight (`/organization`) | `Organization.Read.All` |
| Users | `User.Read.All` |
| Groups | `Group.Read.All` |
| Subscribed license SKUs | `LicenseAssignment.Read.All` |
| Mail-folder metadata | `Mail.ReadBasic.All` |
| Intune managed devices | `DeviceManagementManagedDevices.Read.All` |
| Applications | `Application.Read.All` |
| Service principals | `Application.Read.All` |
| Conditional Access policies | `Policy.Read.All` |

Create an Entra application with a client secret, grant only the permissions
above, and store a JSON object under a vault key, for example
`cloud/m365-readonly`, containing `tenant_id`, `client_id`, and
`client_secret`. Set `credential_ref` to that key. The client secret is
resolved at runtime and never persists in config, evidence, logs, or errors.

Do not grant broad write permissions, `Directory.ReadWrite.All`, or
role-management permissions. If approved user creation is enabled, grant only
the least-privileged `User.Create` application permission (or delegated
permission for a work or school account) in addition to the read permissions
needed by the deployment.

## Live identity, group, license, mailbox, and Intune lookup

The optional live identity connector uses the same Graph read boundary but
accepts an operator-supplied bearer token through settings or the local vault:

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
WAIT_ALLOW_WRITE_ACTIONS=true # required only for approved user creation
```

User creation uses `POST /users` and requires the least-privileged
`User.Create` application permission (or the equivalent delegated permission
with a work or school account). The request requires account state, display
name, mail nickname, user principal name, and a password profile. WAIT stores
only a vault-entry name in the approval request; the temporary password is
resolved from the local vault immediately before the approved request and is
never persisted or returned.

It issues only bounded `GET /users` and `GET /groups` requests plus selected-
field `GET /subscribedSkus`, `GET /users/{id}/mailFolders`, and
`GET /deviceManagement/managedDevices` requests. The separate approved user
creation route issues only `POST /users` with the fixed required fields. User reads can
use an equality filter for a user ID or user principal name. Group reads can
use an equality filter for a group ID, SMTP address, mail nickname, or exact
display name; group members and owners are not expanded. License reads return
tenant subscribed-SKU metadata and aggregate counts, not per-user assignments.
Mailbox reads require an explicit user ID or user principal name and return
selected root mail-folder metadata and aggregate counts; messages, bodies,
attachments, and hidden folders are not requested.
Intune reads use selected inventory and compliance fields; serial numbers, IMEI
values, remote-assistance URLs, and action results are not requested. Microsoft
requires an active Intune tenant license for this API and does not support the
permission for personal Microsoft accounts.
Microsoft documents
`User.Read.All` for application user reads and `User.ReadBasic.All` or
`User.Read.All` for delegated work/school user reads. The Graph groups API
documents group-read permissions for group metadata. The subscribed-SKU API
uses `LicenseAssignment.Read.All` for application or delegated access. Mailbox
folder reads use `Mail.ReadBasic.All` for application access or
`Mail.ReadBasic` for delegated access. The
Intune managed-device API uses `DeviceManagementManagedDevices.Read.All` for
application or delegated access. The
per-user `licenseDetails` API is not used because application permissions are
not supported there. Grant only the permission required by the chosen flow.
The token acquisition flow is deliberately outside WAIT, and this slice does
not create, disable, modify, or assign licenses to users or groups, and does
not mutate mailboxes or Intune devices.
