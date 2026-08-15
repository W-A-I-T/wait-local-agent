# ConnectWise ScreenConnect

ScreenConnect provides tenant-scoped session/device lookup through the RESTful
API Manager extension. An optional local command catalog supports approved
command submission; provider alert/script discovery and polling are not
inferred.

```text
WAIT_SCREENCONNECT_BASE_URL=
WAIT_SCREENCONNECT_EXTENSION_ID=
WAIT_SCREENCONNECT_AUTH_SECRET=
WAIT_SCREENCONNECT_ORIGIN=
WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON={"acme":["session-uuid"]}
WAIT_SCREENCONNECT_SCRIPT_CATALOG_JSON=
WAIT_ALLOW_HTTP_PROBING=true
```

Returned sessions are checked against the explicit tenant map. Command
submission requires the write flag and technician approval. Mocked transport
behavior is covered; live ScreenConnect verification is not claimed.

