# Microsoft 365 cloud inventory permissions

The Microsoft 365 adapter calls Microsoft Graph read endpoints only. For an
application credential, grant administrator-consented application
permissions:

| Inventory | Required permission |
| --- | --- |
| Tenant preflight (`/organization`) | `Organization.Read.All` |
| Users | `User.Read.All` |
| Groups | `Group.Read.All` |
| Applications | `Application.Read.All` |
| Service principals | `Application.Read.All` |
| Conditional Access policies | `Policy.Read.All` |

Create an Entra application with a client secret, grant only the permissions
above, and store a JSON object under a vault key, for example
`cloud/m365-readonly`, containing `tenant_id`, `client_id`, and
`client_secret`. Set `credential_ref` to that key. The client secret is
resolved at runtime and never persists in config, evidence, logs, or errors.

Do not grant write permissions, `Directory.ReadWrite.All`, or role-management
permissions.

## Live identity lookup

The optional live identity connector uses the same Graph read boundary but
accepts an operator-supplied bearer token through settings or the local vault:

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

It issues only `GET /users` requests, optionally with an equality filter for a
user ID or user principal name. Microsoft documents `User.Read.All` for
application user reads; delegated work/school flows may use
`User.ReadBasic.All` or `User.Read.All` according to the requested properties.
The token acquisition flow is deliberately outside WAIT, and this slice does
not create, disable, modify, or license users.
