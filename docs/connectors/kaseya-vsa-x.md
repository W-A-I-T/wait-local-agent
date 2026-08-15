# Kaseya VSA X

Kaseya VSA X provides organization-scoped device and notification reads plus
approval-gated script catalog, preview, execution, and polling.

```text
WAIT_KASEYA_RMM_BASE_URL=
WAIT_KASEYA_RMM_TOKEN_ID=
WAIT_KASEYA_RMM_TOKEN_SECRET=
WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON={"acme":123}
WAIT_KASEYA_RMM_PAGE_SIZE=50
WAIT_ALLOW_HTTP_PROBING=true
```

The documented Basic-auth API is bounded by the explicit client-to-
organization map. Script execution additionally requires the write flag and
technician approval. Fixture/mock coverage is the repository evidence; live
provider verification is not claimed.

