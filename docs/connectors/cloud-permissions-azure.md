# Azure cloud inventory permissions

The Azure adapter performs control-plane reads only. Assign the built-in
`Reader` role at the narrowest subscription or resource-group scope that
covers the inventory, or use a custom role containing these actions:

| Inventory | Required action |
| --- | --- |
| Subscription preflight | `Microsoft.Resources/subscriptions/read` |
| Virtual machines | `Microsoft.Compute/virtualMachines/read` |
| Storage accounts | `Microsoft.Storage/storageAccounts/read` |
| Network security groups | `Microsoft.Network/networkSecurityGroups/read` |
| Role assignments | `Microsoft.Authorization/roleAssignments/read` |

Create an Entra application/service principal with the read-only role and
store a JSON object under a vault key, for example `cloud/azure-readonly`,
containing `tenant_id`, `client_id`, and `client_secret`. Set
`credential_ref` to that key and set `subscription_id` in the collector
config. Secret material is resolved at runtime and is not persisted.

Do not grant Contributor, Owner, User Access Administrator, or any write,
delete, deployment, or role-assignment mutation permission.
