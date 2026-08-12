# Implementation record

- Added `src/wait_local_agent/work_iq.py` as a wrapper over the existing bounded
  `McpClient`.
- Added dedicated `WAIT_WORK_IQ_*` settings and vault-backed token loading.
- Added admin-only `GET /mcp/work-iq/tools` discovery.
- Kept explicit calls library-only and blocked known Work IQ mutation/action
  tool names.
- Documented the preview status, operator token responsibility, and deferred
  OAuth/write/tenant integration.
