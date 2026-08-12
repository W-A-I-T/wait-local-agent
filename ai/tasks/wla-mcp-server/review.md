# Safety review

## Verdict

Acceptable for a bounded, opt-in local integration slice. The endpoint is not
enabled by default and does not introduce a second execution authority.

## Permission and scope risks

- Tool discovery is filtered by the caller's minimum role.
- Non-admin callers require a configured tenant and cannot override it.
- Calls resolve against the same catalog exposed by `tools/list` before they
  reach the existing action service.
- Approval-gated writes remain pending and are never confirmed by this route.

## Prompt injection and data exposure

Tool descriptions are static catalog metadata and are redacted before export.
Caller-provided text is passed only as action input; it does not alter the
catalog or authorization rules. Result values are redacted and internal error
detail is replaced with a generic status message.

## Transport and authentication

The route requires explicit enablement, disabled demo mode, configured bearer
tokens, and at least viewer role. Browser origins require an exact allowlist;
wildcards are not accepted. Requests are bounded to 128 KiB and the adapter
accepts one JSON-RPC object per request. OAuth, remote provisioning, and
server-initiated streaming remain follow-up work.

## Required follow-up

Before external exposure, add a deployment-specific authentication adapter,
TLS/reverse-proxy verification, rate-limit coverage for the new route, and a
Microsoft tenant integration test. Keep the current local bearer-token mode as
the safe default.
