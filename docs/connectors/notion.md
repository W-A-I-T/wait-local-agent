# Notion

Notion supports mapped page search and bounded Markdown retrieval, data-source
metadata and first-page queries, and one approval-gated page-comment write.

```text
WAIT_NOTION_BASE_URL=https://api.notion.com
WAIT_NOTION_API_TOKEN=
WAIT_NOTION_VERSION=2026-03-11
WAIT_NOTION_CLIENT_PAGE_MAP_JSON={"acme":["page-uuid"]}
WAIT_NOTION_CLIENT_DATA_SOURCE_MAP_JSON={"acme":["data-source-uuid"]}
WAIT_NOTION_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

The local client maps are mandatory for reads and scope-checking. Comments
require a preview, approval, probing, and `WAIT_ALLOW_WRITE_ACTIONS=true`;
broader page/property writes remain unavailable. Fixture/mock tests cover the
bounded contract; live Notion verification is not claimed.

