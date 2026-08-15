# ServiceNow

ServiceNow provides bounded incident and company reads. Its governed action
catalog also supports approved work notes, state, assignment, and resolution
metadata updates.

```text
WAIT_SERVICENOW_BASE_URL=
WAIT_SERVICENOW_USERNAME=
WAIT_SERVICENOW_PASSWORD=
WAIT_SERVICENOW_API_VERSION=v1
WAIT_SERVICENOW_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

Reads require probing; writes additionally require the write flag and
technician approval. Credentials are read from settings or the vault and
never action payloads. Mocked/fixture behavior is covered; live ServiceNow
verification is not claimed.

