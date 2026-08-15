# GCP cloud inventory permissions

The GCP adapter uses a service account and read-only APIs. Grant the least
privileged custom role, or equivalent predefined roles, with these
permissions:

| Inventory | Required permission |
| --- | --- |
| Project preflight/discovery | `resourcemanager.projects.get`, `resourcemanager.projects.list` |
| Compute instances | `compute.instances.list` |
| Storage buckets | `storage.buckets.list` |
| Service accounts | `iam.serviceAccounts.list` |

Create a service account, grant it access only to the projects being
inventoried, and store its complete service-account JSON under a vault key,
for example `cloud/gcp-readonly`. Configure the adapter with that key in
`credential_ref` and optionally set `project_id` and `zone`. The JSON is
resolved at runtime and never written to config, results, logs, or errors.

Do not grant roles that include resource creation, update, deletion, IAM
policy administration, or service-account key management.
