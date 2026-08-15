# Syncro

Syncro provides bounded ticket, ticket-comment, and customer reads plus one
tenant-scoped approval-gated ticket-note action.

```text
WAIT_SYNCRO_BASE_URL=
WAIT_SYNCRO_API_TOKEN=
WAIT_ALLOW_HTTP_PROBING=true
```

The note action accepts only the documented subject, body, hidden, and
do-not-email fields. It requires an existing local ticket in tenant scope,
probing, the write flag, and approval. Broader mutations remain unavailable.
Fixture/mock tests cover the contract; live Syncro verification is not
claimed.

