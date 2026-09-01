# Client baseline and drift

WAIT stores versioned, tenant-scoped observations for each client. A snapshot
contains normalized counters and identifiers, source coverage, and an equality
hash. Provider payloads and credentials are not stored; evidence remains
bounded to source references, counts, and as-of timestamps.

The first snapshot is accepted automatically. Later snapshots are candidates
until an administrator accepts one. Accepting a version is atomic, so a
client has at most one accepted baseline.

Drift compares normalized sections rather than presentation order. Findings
are classified as `new`, `changed`, `worsened`, `improved`, `resolved`,
`removed`, or `verification_unavailable`. A source that is blocked,
unconfigured, partial, or failed is never treated as a healthy zero; its
section is excluded from comparison and reported as unavailable.

When an executed, approved change in the same client and comparison window
matches the finding's domain keywords, the result is labelled
`expected_change` and includes the approval reference. Otherwise it is
labelled `no_matching_approved_change`. This is correlation only and never
proves that a change was unauthorized.

The admin API exposes version creation/listing/acceptance below
`/clients/{client_id}` and a live comparison at `/clients/{client_id}/drift`.
Live comparison requires the existing approved read-probing gate.
