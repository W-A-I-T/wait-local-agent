# N-able N-sight

N-sight provides mapped device and health inventory through the documented XML
API, including checks, outages, backup history, patches, antivirus records,
software, and hardware. Patch and antivirus mutations are separate approved
actions.

```text
WAIT_NSIGHT_BASE_URL=https://your-n-sight-server
WAIT_NSIGHT_API_KEY=
WAIT_NSIGHT_CLIENT_MAP_JSON={"acme":123}
WAIT_ALLOW_HTTP_PROBING=true
```

The client map is required; responses are rechecked and bounded. Reads require
outbound probing. Patch, quarantine, and scan actions also require the write
flag, technician approval, and a mapped-device recheck. Fixture and mocked
adapter behavior is covered; live N-sight verification is not claimed.

