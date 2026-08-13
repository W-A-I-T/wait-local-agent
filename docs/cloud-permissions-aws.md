# AWS cloud inventory permissions

The AWS adapter is read-only. Use a dedicated IAM principal with these
actions, scoped to the account and regions being inventoried:

| Inventory | Required action |
| --- | --- |
| Authentication preflight | `sts:GetCallerIdentity` |
| EC2 instances | `ec2:DescribeInstances` |
| Security groups | `ec2:DescribeSecurityGroups` |
| S3 buckets | `s3:ListAllMyBuckets` |
| IAM users | `iam:ListUsers` |

Store a JSON object under a vault key, for example
`cloud/aws-readonly`, containing `aws_access_key_id`,
`aws_secret_access_key`, and optionally `aws_session_token`. Configure the
collector with the key name in `credential_ref`; the credential value is
resolved only at collection time and is never persisted in collector config
or evidence.

Do not grant write, delete, policy, or role-management actions.
