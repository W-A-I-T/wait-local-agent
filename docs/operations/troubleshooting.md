# Troubleshooting

Use this runbook to move from a visible symptom to local evidence. Run the
command in the same installation mode and with the same local configuration as
the affected appliance.

| Symptom | Check | Command | Interpretation |
| --- | --- | --- | --- |
| The appliance will not start, or operator access is rejected | Confirm the Compose services, inspect recent service output, then review startup and access-boundary settings | `docker compose ps`<br>`docker compose logs --tail=300 api ui`<br>`wait-local-agent doctor` | A stopped or restarting service points to startup output. `doctor` reports whether access is required and whether the appliance is in demo mode; it does not print configured secret values. |
| A workflow or Smart Action failed | Find failed runs, then inspect the selected run | `wait-local-agent executions list --status failed`<br>`wait-local-agent executions show <id>`<br>`wait-local-agent analytics summary` | The detail view separates failed steps from completed steps. The summary can show whether the failure is isolated or recurring. A recorded failure is not a successful provider change. |
| You need to review what happened | Read recent audit events or export them for local review | `wait-local-agent audit list`<br>`wait-local-agent audit export <dest> --format json`<br>`wait-local-agent audit export <dest> --format csv` | The audit trail records local decisions and outcomes. An export is evidence from this appliance; it is not proof that every external system accepted a requested change. |
| A connector is not reachable | Review connector readiness and the latest appliance checks | `wait-local-agent connectors list`<br>`wait-local-agent hardening run`<br>`wait-local-agent hardening list` | Connector readiness distinguishes configured surfaces from unavailable ones. Hardening results identify local safety or configuration issues, but do not promise that a provider or network is reachable. |

## Deep links return JSON or 401

When a browser refreshes a known dashboard path such as `/clients` or
`/reports`, the appliance uses the `Accept` header to choose the response. A
request that accepts `text/html` receives the dashboard so the browser can
continue loading that screen. JSON requests, default command-line requests,
and requests without that browser preference continue to receive the API
response, including its normal authentication status. This mirrors the local
development proxy behavior.

## Local API reference

When the local API is running, its interactive documentation is available at
`/docs` on the local API address. It reflects the routes in the running build;
access requirements still apply.

## Before you share logs

Remove secrets, tokens, URLs, customer data, and ticket bodies. Review exported
files as well as copied console output before sharing either one.

The planned redacted-bundle flow is defined in [Diagnostics &
Support](diagnostics-and-support.md).
