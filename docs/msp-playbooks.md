# MSP playbooks

WAIT now exposes a bounded MSP playbook catalog over the existing workflow
templates, smart actions, report builders, approval records, audit events, and
tenant scope. A playbook is an ordered, versioned local definition; it is not a
second agent or provider execution engine.

The current built-in catalog includes:

- ticket intake, resolution, dispatch, stale/SLA, and security-response reviews;
- Microsoft 365 onboarding and offboarding reviews; and
- QBR, automation-opportunity, and recurring-service-review reports.

Preview is side-effect free. It validates the complete ordered definition,
shows each workflow or report step, exposes required inputs and approval/risk
boundaries, and returns the unsupported provider or automation claims. Use:

```text
POST /msp/playbooks/{playbook_id}/preview
```

Execution runs steps in definition order through the existing workflow and
report services. A pending approval or failed step stops later steps. The
result includes child workflow or report IDs, evidence status where the report
service provides it, output-evidence labels, and a bounded unsupported list.
Execution records `msp.playbook.started` and either
`msp.playbook.completed` or `msp.playbook.stopped` in the existing audit log.
Use:

```text
POST /msp/playbooks/{playbook_id}/runs
```

The same surface is available from the local CLI:

```text
wait-local-agent workflows playbooks
wait-local-agent workflows playbook-preview security-response-review TCK-1001
wait-local-agent workflows playbook-run security-response-review TCK-1001
```

## Published aggregate lifecycle

The local catalog can also publish a tenant-scoped copy of a built-in (or a
validated local definition). Published entries retain their source identifier,
provenance, enabled state, current version, and immutable snapshots in SQLite.
Only workflow-template and report steps from the existing WAIT catalog are
accepted; arbitrary shell commands, provider calls, and a second agent engine
are not valid playbook steps.

The lifecycle is available through:

```text
GET  /msp/playbook-entries
POST /msp/playbook-entries
PATCH /msp/playbook-entries/{entry_id}
POST /msp/playbook-entries/{entry_id}/enable
POST /msp/playbook-entries/{entry_id}/disable
GET  /msp/playbook-entries/{entry_id}/revisions
GET  /msp/playbook-entries/{entry_id}/revisions/diff?from_version=1&to_version=2
POST /msp/playbook-entries/{entry_id}/revisions/{version}/restore
```

The equivalent local commands are `workflows playbook-entries`,
`playbook-entry-publish`, `playbook-entry-update`,
`playbook-entry-revisions`, `playbook-entry-diff`, and
`playbook-entry-restore`. Updates and restores create a new version rather than
rewriting history. Entries are tenant-filtered using the authenticated scope;
preview and run reject disabled entries before any child workflow or report is
created.

This slice is local and evidence-backed. It does not claim live provider
success, vendor SLA compliance, measured time savings, or automatic ticket
merge/close. Those values remain explicitly unsupported unless a future
provider contract and stored evidence establish them.

The broader MSP issue remains open. Built-in versioned definitions and the
preview/controlled-run contract plus the first tenant-edited aggregate
publish/disable/restore/compare lifecycle slice are now present. Richer step
input mappings, provider-backed historical ingestion, and several scheduled or
event-triggered operations remain follow-up work. The existing workflow gallery
continues to provide lifecycle operations for individual templates.
