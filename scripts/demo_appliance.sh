#!/usr/bin/env bash
set -euo pipefail

wait-local-agent doctor
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets
wait-local-agent tickets summarize TCK-1001
wait-local-agent workflows templates
wait-local-agent workflows run ticket-triage TCK-1001
wait-local-agent connectors list
wait-local-agent events list
