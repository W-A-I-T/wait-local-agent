# VPN Application Troubleshooting Runbook

Use this runbook when VPN connects but an internal application fails to load.

1. Confirm VPN authentication succeeded and note the assigned VPN IP range.
2. Check DNS resolution for the application hostname from the affected endpoint.
3. Confirm the route to the application subnet is present after VPN connection.
4. Compare behavior from another known-good VPN user.
5. Escalate to network engineering only after DNS and route evidence is captured.

Client-safe update:

```text
We confirmed the VPN tunnel is connecting. We are checking DNS and routing to the application subnet before escalating to network engineering.
```
