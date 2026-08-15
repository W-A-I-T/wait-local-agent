# Confluence Cloud

Confluence Cloud provides bounded read-only page listing and detail through
REST API v2.

```text
WAIT_CONFLUENCE_BASE_URL=
WAIT_CONFLUENCE_EMAIL=
WAIT_CONFLUENCE_API_TOKEN=
WAIT_CONFLUENCE_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

Use `connectors validate confluence`, `confluence-health`, `confluence-pages`,
and `confluence-page`. Credentials are read from settings or the vault,
network access is opt-in, and page writes are unavailable. Mocked/fixture
behavior is the available evidence; live verification is not claimed.

