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

## Read response envelope

ConnectWise read methods retain the existing `result` and `items` values and
add poll-safe metadata: `raw_count` counts candidate entries before
normalization, `dropped_count` counts candidates that did not become normalized
items, `http_status` records the response status when one was received, and
`retry_after` records a valid seconds or HTTP-date delay for HTTP 429/503.
Only a valid 2xx empty list is an end-of-page signal. All-dropped pages,
malformed list envelopes, 3xx responses, blocked or not-configured reads, and
transport/HTTP failures are not EOF. Normalized subject/company fields are
capped at 512 characters, descriptions at 8192, and status/priority fields at
128.
