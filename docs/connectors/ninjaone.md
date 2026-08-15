# NinjaOne RMM

WAIT exposes tenant-scoped device and alert inventory, script metadata and
preview, bounded execution lookup, and approval-aware script execution.

```text
WAIT_NINJAONE_BASE_URL=https://app.ninjarmm.com/api/v2
WAIT_NINJAONE_ACCESS_TOKEN=
WAIT_NINJAONE_ORGANIZATION_MAP_JSON={"acme":42}
WAIT_NINJAONE_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

`WAIT_NINJAONE_ORGANIZATION_MAP_JSON` is the local client-to-organization map.
Returned rows are rechecked against it. Reads require outbound probing; script
execution additionally requires `WAIT_ALLOW_WRITE_ACTIONS=true` and technician
approval. Use `connectors validate ninjaone` only when explicitly configured.
Fixture and mocked transport tests cover scope filtering and blocked/error
paths; live provider verification is not part of this repository's evidence.

