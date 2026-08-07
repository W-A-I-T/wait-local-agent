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
