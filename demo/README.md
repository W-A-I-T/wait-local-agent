# Demo Data

This directory contains synthetic, public-safe data for screenshots, walkthroughs, and launch demos.

- `sample_tickets/tickets.json` contains fictional MSP service desk tickets.
- `sample_runbooks/` contains fictional runbooks for local knowledge ingestion.

The automated CLI demo still uses `examples/` because those fixtures are covered by the test suite. The `demo/` data is intentionally separate so launch assets can evolve without weakening regression tests.

To run the same flow against this demo data:

```bash
WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent knowledge ingest demo/sample_runbooks

WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent ingest demo/sample_tickets

WAIT_DATA_PATH=.wait-local-agent/demo.db \
WAIT_ALLOWED_DOC_ROOT=demo/sample_runbooks \
wait-local-agent tickets summarize DEMO-1001
```
