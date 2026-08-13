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

Tenant-owned aggregate definitions use the same execution boundary and are
persisted separately from the built-in catalog. Create a definition with
`POST /msp/playbooks/custom`, edit or disable it with
`PATCH /msp/playbooks/custom/{entry_id}`, and inspect its immutable revisions
with `GET /msp/playbooks/custom/{entry_id}/revisions`. A restore creates a new
version rather than rewriting history; the revision diff endpoint compares two
stored envelopes. Definitions may reference only existing WAIT workflow
templates or supported local report types, and new entries are disabled until
explicitly enabled.

The same surface is available from the local CLI:

```text
wait-local-agent workflows playbooks
wait-local-agent workflows playbook-preview security-response-review TCK-1001
wait-local-agent workflows playbook-run security-response-review TCK-1001
```

This slice is local and evidence-backed. It does not claim live provider
success, vendor SLA compliance, measured time savings, or automatic ticket
merge/close. Those values remain explicitly unsupported unless a future
provider contract and stored evidence establish them.

The broader MSP issue remains open. Built-in and tenant-owned versioned
definitions, disabled-by-default publishing, revision restore/diff, and the
preview/controlled-run contract are now present. Richer step input mappings,
provider-backed historical ingestion, and several scheduled or event-triggered
operations remain follow-up work. The existing workflow gallery continues to
provide lifecycle operations for individual templates.
