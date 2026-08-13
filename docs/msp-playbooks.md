# MSP playbooks

WAIT now exposes a bounded MSP playbook catalog over the existing workflow
templates, smart actions, report builders, approval records, audit events, and
tenant scope. A playbook is an ordered, versioned local definition; it is not a
second agent or provider execution engine.

The current built-in catalog includes:

- ticket intake, resolution, dispatch, stale/SLA, and security-response reviews;
- inactive-ticket follow-up review;
- Microsoft 365 onboarding, offboarding, password-reset, explicit
  authentication-method removal, license, and read-only compliance reviews; and
- read-only software-inventory review for one explicitly mapped N-sight device; and
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

## Scheduled playbooks

Any validated static or tenant-published playbook can also be registered as a
scheduled job through the existing scheduler:

```text
POST /scheduled-jobs
{
  "playbook_id": "qbr-review",
  "schedule_type": "interval",
  "interval_seconds": 86400,
  "params": {
    "client_id": "acme",
    "input": {"period_start": "2026-01-01", "period_end": "2026-01-31"}
  }
}
```

Workflow playbooks use `params.ticket_id`; report playbooks use the explicit
client scope and report period inputs. Registration performs the same
side-effect-free preview validation as the manual preview route. When the
schedule fires, the existing `SchedulerManager` invokes `run_msp_playbook`,
so workflow steps retain their normal approval, tenant, audit, and completion
event boundaries. A schedule is execution evidence only after its triggered
playbook result is recorded; it does not imply provider success.

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

## Event-triggered subscriptions

Workflow playbooks whose declared trigger is one of the existing bounded event
types can be subscribed for one tenant. Subscription creation requires an
exact trigger match, an explicit client scope, and an optional bounded mapping
from top-level event fields to playbook inputs. No provider callback or
arbitrary event type is inferred.

```text
POST /msp/playbook-subscriptions
GET  /msp/playbook-subscriptions
PATCH /msp/playbook-subscriptions/{subscription_id}
POST /msp/playbook-subscriptions/{subscription_id}/enable
POST /msp/playbook-subscriptions/{subscription_id}/disable
```

The existing `EventDispatcher` invokes the existing playbook coordinator,
persists matched subscription IDs, playbook run IDs, bounded attempt state,
and redacted errors on the tenant-scoped event delivery, and preserves the
playbook's normal approval pause. Event idempotency prevents a duplicate
delivery from starting the playbook again. The equivalent CLI commands are
`workflows playbook-subscribe`, `playbook-subscriptions`, and
`playbook-subscription-update`.

This slice is local and evidence-backed. It does not claim live provider
success, vendor SLA compliance, measured time savings, or automatic ticket
merge/close. Those values remain explicitly unsupported unless a future
provider contract and stored evidence establish them.

The broader MSP issue remains open. Built-in versioned definitions and the
preview/controlled-run contract plus the first tenant-edited aggregate
publish/disable/restore/compare lifecycle slice plus scheduled playbook
registration and execution through the existing scheduler are now present.
Richer provider-backed step mappings and historical/provider ingestion remain
follow-up work. The M365 compliance review
reads bounded managed-device and tenant-license Graph evidence and classifies
only observed device/license attention states; it does not assert regulatory
compliance or provider success. The other new M365 playbooks prepare and gate requests; they
do not claim a live directory mutation without configured provider evidence. The
software-inventory review reuses the existing N-sight mapped-device inventory
read and does not claim vulnerability status, installation/removal, or
remediation. The
existing workflow gallery continues to provide lifecycle operations for
individual templates.
