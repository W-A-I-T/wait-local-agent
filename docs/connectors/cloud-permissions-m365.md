# Microsoft 365 cloud inventory permissions

The Microsoft 365 adapter calls bounded Microsoft Graph read endpoints and
approval-gated user lifecycle endpoints. For an
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
| Approved user disable/offboarding | `User.EnableDisableAccount.All` and `User.Read.All` |
| Approved group membership changes | `GroupMember.ReadWrite.All` |
| Approved direct user license changes | `LicenseAssignment.ReadWrite.All` |
| Approved session revocation | `User.RevokeSessions.All` |
| Approved password reset | `User-PasswordProfile.ReadWrite.All` |
| Approved authentication-method removal | `UserAuthenticationMethod.ReadWrite.All` |
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
For approved direct user license changes, grant only the least-privileged
`LicenseAssignment.ReadWrite.All` application permission; do not grant
`Directory.ReadWrite.All`.
For approved session revocation, grant only the least-privileged application
permission `User.RevokeSessions.All`.
For approved disable/offboarding, grant only the least-privileged application
combination `User.EnableDisableAccount.All` and `User.Read.All` described by
Microsoft Graph; do not grant `Directory.ReadWrite.All`.
For approved password reset, grant only `User-PasswordProfile.ReadWrite.All` and
use the local-vault password flow; WAIT never accepts the password in an API
payload. For approved authentication-method removal, grant only
`UserAuthenticationMethod.ReadWrite.All`; the action accepts one method type and
ID and does not remove all methods.

## Live identity, group, license, mailbox, and Intune lookup

The optional live identity connector uses the same Graph read boundary but
accepts an operator-supplied bearer token through settings or the local vault:

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
WAIT_ALLOW_WRITE_ACTIONS=true # required only for approved M365 writes
```

Graph reads retry HTTP 429, 502, 503, and 504 responses at most three times.
`Retry-After` is honored when supplied, with a 30-second per-wait and
60-second total-wait cap; writes are never retried. Client-credential tokens
are refreshed five minutes before expiry by default. An oversized pagination
cursor fails the read instead of silently truncating the inventory.

The API classifies provider failures consistently: throttling returns HTTP 429
with `detail.code` `m365_throttled` and, when available,
`retry_after_seconds`; authentication failures return HTTP 502 with
`m365_auth_required`; missing Graph permission returns HTTP 403 with
`m365_insufficient_permission`; and provider or pagination failures return
HTTP 503 or 502 respectively. These responses contain sanitized messages only.

User creation uses `POST /users` and requires the least-privileged
`User.Create` application permission (or the equivalent delegated permission
with a work or school account). The request requires account state, display
name, mail nickname, user principal name, and a password profile. WAIT stores
only a vault-entry name in the approval request; the temporary password is
resolved from the local vault immediately before the approved request and is
never persisted or returned.

Its read surface issues only bounded `GET /users` and `GET /groups` requests plus selected-
field `GET /subscribedSkus`, `GET /users/{id}/mailFolders`, and
`GET /deviceManagement/managedDevices` requests. The separate approved user
creation route issues only `POST /users` with the fixed required fields. The
approved disable/offboarding route issues only `PATCH /users/{id |
userPrincipalName}` with `{"accountEnabled": false}`. It does not revoke
sign-in sessions, remove licenses or group memberships, mutate mailbox data,
or act on Intune devices. The approved group membership route uses only
`POST /groups/{id}/members/$ref` for add and
`DELETE /groups/{id}/members/{id}/$ref` for remove, always retaining `/$ref`
to prevent deleting the directory object. It accepts immutable group and user
IDs only and requires `GroupMember.ReadWrite.All`. The approved direct user
license route uses only `POST /users/{id | userPrincipalName}/assignLicense`,
accepts immutable user IDs and canonical SKU GUIDs, and requires
`LicenseAssignment.ReadWrite.All`; it supports only explicit add or remove
operations. The separate approved session-revocation route uses only
`POST /users/{id | userPrincipalName}/revokeSignInSessions` with no request
body, accepts immutable user IDs, and requires `User.RevokeSessions.All`.
User reads can
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
The token acquisition flow is deliberately outside WAIT. Microsoft documents
the [user update](https://learn.microsoft.com/en-us/graph/api/user-update?view=graph-rest-1.0)
endpoint and the [Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
and [user assignLicense](https://learn.microsoft.com/en-us/graph/api/user-assignlicense?view=graph-rest-1.0),
and [revokeSignInSessions](https://learn.microsoft.com/en-us/graph/api/user-revokesigninsessions?view=graph-rest-1.0)
for these lifecycle permissions. Session revocation is a separate
`revokeSignInSessions` action and is intentionally not part of this slice.

The password-reset action uses `PATCH /users/{id | userPrincipalName}` with only
the documented `passwordProfile` fields. Authentication-method removal uses the
documented method-specific `DELETE /users/{id | userPrincipalName}/authentication/...`
resources for FIDO2, Microsoft Authenticator, phone, and software OATH methods.
WAIT does not claim support for other method families or reset-all behavior. See
Microsoft's [passwordProfile resource](https://learn.microsoft.com/en-us/graph/api/resources/passwordprofile?view=graph-rest-1.0),
[authentication-method permissions](https://learn.microsoft.com/en-us/graph/api/authentication-list-methods?view=graph-rest-1.0),
[FIDO2 deletion](https://learn.microsoft.com/en-us/graph/api/fido2authenticationmethod-delete?view=graph-rest-1.0),
[phone deletion](https://learn.microsoft.com/en-us/graph/api/phoneauthenticationmethod-delete?view=graph-rest-1.0),
and [software OATH deletion](https://learn.microsoft.com/en-us/graph/api/softwareoathauthenticationmethod-delete?view=graph-rest-1.0)
for the provider contract.
