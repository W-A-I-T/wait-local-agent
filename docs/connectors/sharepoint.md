# SharePoint

SharePoint provides bounded Microsoft Graph site and document-library
metadata, folder-scoped listing, and an explicit content search surface.

```text
WAIT_SHAREPOINT_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_SHAREPOINT_ACCESS_TOKEN=
WAIT_SHAREPOINT_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

Use the validate, health, site, and document read commands. The bearer token
stays in settings or the vault; Graph reads require explicit probing. No
SharePoint write action is exposed. Mocked/fixture coverage is the available
evidence; live verification is not claimed.

