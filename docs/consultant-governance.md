# Consultant governance review

The governance evaluator reviews a generated consultant architecture and
optional generated connector artifacts against fixed safe defaults. It flags
unresolved architecture items, external system boundaries, authentication
review requirements, connector write actions without an approval boundary, and
any credential material present in an artifact.

It is a report-only surface. It does not change authorization, approve a write,
execute a connector, contact a tenant, or deploy a solution.
It also emits an explicit policy mapping for credential absence, approval for
state changes, tenant-scoped external access, and human approval before
deployment. `pass` means the supplied evidence satisfied that policy for the
review; `needs_review` is not an authorization grant.

API:

```text
POST /consultant/governance/evaluate
```

CLI input is a JSON object containing `architecture` and optional
`connector_artifacts`:

```bash
wait-local-agent microsoft governance evaluate governance.json
```

The result includes severity counts, redacted connector metadata, and explicit
`authorization_changed`, `execution_started`, and `deployment_started` false
flags. A solution with findings is `needs_review`; only a fully resolved
read-only architecture can report `pass`.
