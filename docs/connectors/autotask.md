# Autotask PSA

Autotask provides bounded ticket and company reads and approved ticket-note,
time-entry, status, resolution, and assignment actions.

```text
WAIT_AUTOTASK_BASE_URL=
WAIT_AUTOTASK_USERNAME=
WAIT_AUTOTASK_SECRET=
WAIT_AUTOTASK_INTEGRATION_CODE=
WAIT_AUTOTASK_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

Write fields are explicit operator inputs; broader mutations are unavailable.
Reads require probing, and writes additionally require the write flag and
technician approval. Fixture/mock coverage is the repository evidence; live
Autotask verification is not claimed.

