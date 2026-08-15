# Datto RMM

The Datto adapter provides tenant-scoped device and open-alert inventory,
component metadata, quick-job preview/execution, and bounded job status.

```text
WAIT_DATTORMM_BASE_URL=https://your-datto-api-host/api
WAIT_DATTORMM_ACCESS_TOKEN=
WAIT_DATTORMM_SITE_MAP_JSON={"acme":"site-uid"}
WAIT_DATTORMM_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

The local client-to-site map is mandatory and returned provider rows are
scope-checked. Quick jobs require probing, the write flag, and technician
approval. Mocked transport coverage verifies mapping, pagination, blocked
HTTP, malformed responses, and approval gates; live provider verification is
not claimed.

