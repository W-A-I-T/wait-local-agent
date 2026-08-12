# Safety review

## Verdict

Acceptable as an opt-in discovery client. It does not create a new local tool
authority or silently execute remote tools.

## Permission and scope risks

The API surface is admin-only and discovery-only. Remote tools are not merged
into local `/tools`, and the generic call method is not exposed over HTTP.
Remote execution still needs an approval record, tenant mapping, and evidence
contract before it can be product-facing.

## Prompt injection exposure

Remote descriptions, titles, schemas, and results are untrusted. Metadata is
normalized, bounded, marked as untrusted, and redacted. The client never uses
remote descriptions to select or register tools; named calls require an
explicit caller-supplied name.

## Transport and auth risks

Outbound traffic requires client enablement, HTTP probing enablement, an HTTPS
URL, an exact host allowlist, and a dedicated bearer token. Redirects are
disabled. Remote HTTP error bodies and JSON-RPC error text are not returned.

## Missing tests and remediations

Deployment TLS/DNS verification, token rotation, remote server conformance,
and approval-backed remote execution remain required before production use.
Add those in the connector-specific or deployment integration slice rather
than broadening this generic client.
