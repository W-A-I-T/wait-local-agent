# ConnectWise PSA

ConnectWise PSA provides ticket and company lookup plus an allowlisted,
approval-gated ticket update path.

```text
WAIT_CONNECTWISE_BASE_URL=
WAIT_CONNECTWISE_COMPANY=
WAIT_CONNECTWISE_PUBLIC_KEY=
WAIT_CONNECTWISE_PRIVATE_KEY=
WAIT_CONNECTWISE_CLIENT_ID=
WAIT_CONNECTWISE_API_VERSION=2022.1
WAIT_ALLOW_HTTP_PROBING=true
```

Ticket writes support only `update_status`, `assign_technician`, and
`update_ticket_fields`. They require probing, `WAIT_ALLOW_WRITE_ACTIONS=true`,
a pending draft, and technician approval. Credentials and provider IDs do not
come from action payloads. Mocked/fixture tests cover the guarded path; live
verification is not claimed.

