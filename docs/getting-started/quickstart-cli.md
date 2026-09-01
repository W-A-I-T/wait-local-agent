# CLI Quickstart

Create a development environment and install the local package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
wait-local-agent doctor
```

The deterministic demo path is:

```bash
export WAIT_DEMO_MODE=true
export WAIT_ALLOW_WRITE_ACTIONS=false
scripts/demo_appliance.sh
```

The script calls the explicit `wait-local-agent demo seed` command. Demo data
is never seeded merely because a process starts in a non-demo deployment.

Representative local checks include:

```bash
wait-local-agent knowledge ingest examples/sample_docs
wait-local-agent ingest examples/sample_tickets --client-id acme
wait-local-agent tickets summarize TCK-1002
wait-local-agent workflows templates
wait-local-agent workflows run documentation-assisted-response TCK-1002
wait-local-agent agents list
wait-local-agent approvals list
wait-local-agent events list
wait-local-agent connectors list
wait-local-agent update check
```

Connector validation and live reads remain blocked until the relevant
credentials and explicit outbound setting are configured. Writes additionally
require the write setting and the applicable approval flow.
