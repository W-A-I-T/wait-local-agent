# N-able N-central

N-central supports bounded tenant-scoped device, active-issue, scheduled-task
metadata, direct-task submission, and status lookup.

```text
WAIT_NCENTRAL_BASE_URL=https://your-ncentral-host
WAIT_NCENTRAL_ACCESS_TOKEN=
WAIT_NCENTRAL_ORG_UNIT_MAP_JSON={"acme":[100,101]}
WAIT_NCENTRAL_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

Requests require a mapped WAIT client and results are filtered to its
organization units. Direct task submission is limited to an existing numeric
task and in-scope numeric device and requires the write flag plus technician
approval. Tests cover bounded and blocked behavior; live verification is not
claimed.

