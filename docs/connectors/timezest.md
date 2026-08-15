# TimeZest

TimeZest exposes tenant-mapped scheduling-request reads and one documented
approval-gated create action. Reschedule and cancel mutations are not inferred.

```text
WAIT_TIMEZEST_BASE_URL=https://api.timezest.com
WAIT_TIMEZEST_API_KEY=
WAIT_TIMEZEST_CLIENT_MAP_JSON={"acme":{"connectwise_psa_company_id":209116}}
WAIT_ALLOW_HTTP_PROBING=true
```

Returned associated entities are checked against the local map. Reads require
probing; a create requires probing, the write flag, a provider key, and
technician approval. Mocked contract tests are the available evidence; live
TimeZest verification is not claimed.

