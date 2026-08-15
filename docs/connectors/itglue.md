# IT Glue

IT Glue is a read-only, organization-scoped documentation connector for
organizations, documents, folders, and bounded document-content search.

```text
WAIT_ITGLUE_BASE_URL=
WAIT_ITGLUE_API_KEY=
WAIT_ITGLUE_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

Validate with `wait-local-agent connectors validate itglue`. Credentials stay
in settings or the vault, outbound calls require explicit probing, and no
write surface is exposed. Fixture/mock coverage is present; live IT Glue
verification is not claimed.

