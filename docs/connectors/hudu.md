# Hudu

Hudu is a read-only documentation connector for company and article lookup.

```text
WAIT_HUDU_BASE_URL=
WAIT_HUDU_API_KEY=
WAIT_HUDU_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

Use `wait-local-agent connectors validate hudu`, then the health, company, and
article read commands. Credentials remain in settings or the local vault;
there is no Hudu write action. Fixture/mock behavior and blocked outbound
requests are tested; live Hudu verification is not claimed.

